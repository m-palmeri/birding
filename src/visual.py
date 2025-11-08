#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv
from pathlib import Path
import pandas as pd
from utils import ensure_dir, download_asset, build_filename

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--media_dir", required=True)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    out_dir = Path(args.out_dir); ensure_dir(out_dir)
    media_dir = Path(args.media_dir); ensure_dir(media_dir)

    df = pd.read_csv(args.input)
    for c in ["ML_ID","Species"]:
        if c not in df.columns: raise SystemExit(f"Missing required column: {c}")
    if "Tags" not in df.columns: df["Tags"] = ""

    rows, errors = [], []

    for _, row in df.iterrows():
        mlid = str(row["ML_ID"]).strip()
        species = str(row["Species"]).strip()
        tags = str(row["Tags"]).strip()

        tmp_base = media_dir / f"tmp_{mlid}"
        try:
            tmp_path_str = download_asset(mlid, tmp_base, session=None, delay=args.delay)
        except Exception as e:
            errors.append((mlid, f"download error: {e!r}")); continue

        tmp_path = Path(tmp_path_str)
        final_name = build_filename(species, mlid, tmp_path.suffix, suffix=None)
        final_path = media_dir / final_name

        try: tmp_path.rename(final_path)
        except Exception:
            final_path.write_bytes(tmp_path.read_bytes())
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass

        img_tag = f'<img src="{final_name}">'
        front = f'What is this bird?<br>{img_tag}'
        back = f"{species}"
        rows.append({"Front": front, "Back": back, "Media": img_tag, "Species": species, "ML": f"ML{mlid}", "Tags": tags})

    out_csv = out_dir / "anki_import_visual.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Front","Back","Media","Species","ML","Tags"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    if errors:
        err_csv = out_dir / "errors_visual.csv"
        with open(err_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["ML_ID","Error"]); w.writerows(errors)

    print(f"✅ Wrote {len(rows)} visual notes to {out_csv}")
    print(f"🖼  Media in: {media_dir.resolve()}")
    if errors: print(f"⚠️ Errors logged to: {err_csv}")

if __name__ == "__main__":
    main()
