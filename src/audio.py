#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, os
from pathlib import Path
from typing import Optional
# audioop shim for Python 3.13
try:
    import audioop  # noqa: F401
except ModuleNotFoundError:
    try:
        import pyaudioop as audioop  # type: ignore # noqa: F401
    except Exception:
        pass
import pandas as pd
from pydub import AudioSegment
from utils import ensure_dir, parse_time_to_ms, download_asset, build_filename

def export_audio(src_path: Path, dest_path: Path, clip_start_ms: Optional[int], clip_end_ms: Optional[int]) -> str:
    audio = AudioSegment.from_file(src_path)
    duration = len(audio)
    s = clip_start_ms if clip_start_ms is not None else 0
    e = clip_end_ms if clip_end_ms is not None else duration
    s = max(0, s); e = max(s, min(e, duration))
    clip = audio[s:e] if (s != 0 or e != duration) else audio

    ext = src_path.suffix.lower().lstrip(".")
    export_kwargs = {"format": ext}
    if ext == "m4a": export_kwargs["format"] = "ipod"
    if ext == "mp3": export_kwargs["bitrate"] = "128k"
    clip.export(dest_path, **export_kwargs)
    return str(dest_path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out_dir", default = "./out")
    ap.add_argument("--media_dir", default = os.path.expanduser("~/Library/Application Support/Anki2/User 1/collection.media"))
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    out_dir = Path(args.out_dir); ensure_dir(out_dir)
    media_dir = Path(args.media_dir); ensure_dir(media_dir)

    import pandas as pd
    df = pd.read_csv(args.input)
    for c in ["ML_ID","Species"]:
        if c not in df.columns: raise SystemExit(f"Missing required column: {c}")
    if "ClipStart" not in df.columns: df["ClipStart"] = ""
    if "ClipEnd" not in df.columns: df["ClipEnd"] = ""
    if "Tags" not in df.columns: df["Tags"] = ""

    rows, errors = [], []

    for _, row in df.iterrows():
        mlid = str(row["ML_ID"]).strip()
        species = str(row["Species"]).strip()
        tags = str(row["Tags"]).strip()
        start_ms = parse_time_to_ms(row["ClipStart"])
        end_ms = parse_time_to_ms(row["ClipEnd"])

        tmp_base = media_dir / f"tmp_{mlid}"
        try:
            tmp_path = Path(download_asset(mlid, tmp_base, session=None, delay=args.delay))
        except Exception as e:
            errors.append((mlid, f"download error: {e!r}")); continue

        final_name = build_filename(species, mlid, tmp_path.suffix, suffix=None)
        final_path = media_dir / final_name
        try:
            export_audio(tmp_path, final_path, start_ms, end_ms)
        except Exception as e:
            errors.append((mlid, f"trim/export error: {e!r}"))
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass
            continue

        try: tmp_path.unlink(missing_ok=True)
        except Exception: pass

        front = "What is this bird?"
        back = f"{species}"
        media_field = f"[sound:{final_name}]"
        rows.append({"Front": front, "Back": back, "Media": media_field, "Species": species, "ML": f"ML{mlid}", "Tags": tags})

    out_csv = out_dir / "anki_import_audio.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Front","Back","Media","Species","ML","Tags"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    if errors:
        err_csv = out_dir / "errors_audio.csv"
        with open(err_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["ML_ID","Error"]); w.writerows(errors)

    print(f"✅ Wrote {len(rows)} audio notes to {out_csv}")
    print(f"🎧 Media in: {media_dir.resolve()}")
    if errors: print(f"⚠️ Errors logged to: {err_csv}")

if __name__ == "__main__":
    main()
