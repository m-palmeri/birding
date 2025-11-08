#!/usr/bin/env python3
"""
ML CDN → Anki: Direct Audio Downloader + Trimmer

Given an input CSV with:
  ML_ID, Species, ClipStart, ClipEnd, Tags (optional)

This script:
  1) Downloads the audio file from:
     https://cdn.download.ams.birds.cornell.edu/api/v1/asset/<ML_ID>
  2) Trims the audio to ClipStart..ClipEnd if provided
  3) Writes an Anki-importable CSV:
     Front="What is this bird?"
     Back = "<Species>"
     Audio = "[sound:<filename>]"
     Species, ML, Tags as extra fields

Output:
  out/media/  -> audio files
  out/anki_import.csv

Dependencies:
  - requests
  - pandas
  - pydub (requires ffmpeg installed on your system)
    * macOS: brew install ffmpeg
    * Windows: choco install ffmpeg  (or download binaries)
    * Linux: apt-get install ffmpeg

Usage:
  python ml_cdn_to_anki.py --input input.csv --out_dir ./out

CSV details:
  - ClipStart/ClipEnd can be blank or formatted as:
      * seconds as float: "12.5"
      * mm:ss or mm:ss.s
      * hh:mm:ss or hh:mm:ss.s
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import pandas as pd
from pydub import AudioSegment

HEADERS = {"User-Agent": "ML-CDN-to-Anki/1.0"}

CDN_TMPL = "https://cdn.download.ams.birds.cornell.edu/api/v1/asset/{mlid}"

def parse_time(s: str) -> Optional[int]:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        if ":" not in s:
            return int(float(s) * 1000)
        parts = [p.strip() for p in s.split(":")]
        if len(parts) == 2:
            mm, ss = parts
            mm = int(mm); ss = float(ss)
            return int((mm * 60 + ss) * 1000)
        elif len(parts) == 3:
            hh, mm, ss = parts
            hh = int(hh); mm = int(mm); ss = float(ss)
            return int(((hh * 3600) + (mm * 60) + ss) * 1000)
        else:
            return None
    except Exception:
        return None

def clean_name(s: str) -> str:
    import re
    s = s.strip()
    s = re.sub(r"[^\w\-\.\(\) ]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s

def infer_extension_from_headers(resp) -> str:
    ctype = resp.headers.get("Content-Type","").lower()
    if "m4a" in ctype or "mp4" in ctype:
        return ".m4a"
    if "mpeg" in ctype or "mp3" in ctype:
        return ".mp3"
    cd = resp.headers.get("Content-Disposition","")
    for ext in [".m4a",".mp3",".wav"]:
        if ext in cd.lower():
            return ext
    return ".mp3"

def build_filename(species: str, mlid: str, ext: str, clipstart_ms: Optional[int], clipend_ms: Optional[int]) -> str:
    base = f"{species}_ML{mlid}".strip("_")
    if clipstart_ms is not None or clipend_ms is not None:
        a = f"{int((clipstart_ms or 0)/1000)}"
        b = f"{int((clipend_ms or 0)/1000)}" if clipend_ms is not None else ""
        base += f"_{a}-{b}"
    return clean_name(base) + ext

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path("~/Library/Application Support/Anki2/User 1/collection.media").expanduser()

    df = pd.read_csv(args.input)
    for col in ["ML_ID","Species"]:
        if col not in df.columns:
            sys.exit(f"Missing required column: {col}")
    if "ClipStart" not in df.columns: df["ClipStart"] = ""
    if "ClipEnd" not in df.columns: df["ClipEnd"] = ""
    if "Tags" not in df.columns: df["Tags"] = ""

    import csv as _csv
    errors = []
    anki_rows = []

    session = requests.Session()

    for _, row in df.iterrows():
        mlid = str(row["ML_ID"]).strip()
        species = str(row["Species"]).strip()
        tags = str(row["Tags"]).strip()

        start_ms = parse_time(row["ClipStart"])
        end_ms = parse_time(row["ClipEnd"])

        # 1) Download
        url = CDN_TMPL.format(mlid=mlid)
        try:
            r = session.get(url, headers=HEADERS, stream=True, timeout=60)
            if r.status_code != 200:
                errors.append((mlid, f"HTTP {r.status_code}"))
                continue
            ext = infer_extension_from_headers(r)
            tmp_path = media_dir / f"tmp_{mlid}{ext}"
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            errors.append((mlid, f"download error: {e!r}"))
            continue

        # 2) Trim (if requested)
        try:
            audio = AudioSegment.from_file(tmp_path)
            duration = len(audio)
            s = start_ms if start_ms is not None else 0
            e = end_ms if end_ms is not None else duration
            s = max(0, s); e = max(s, min(e, duration))
            clip = audio[s:e] if (s != 0 or e != duration) else audio

            # keep original extension
            fname = build_filename(species, mlid, ext, start_ms, end_ms)
            out_path = media_dir / fname
            export_kwargs = {"format": ext.lstrip(".")}
            # pydub/ffmpeg needs special alias for m4a
            if ext == ".m4a":
                export_kwargs["format"] = "ipod"  # AAC in MP4 container
            if ext == ".mp3":
                export_kwargs["bitrate"] = "128k"
            clip.export(out_path, **export_kwargs)
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as e:
            errors.append((mlid, f"trim/export error: {e!r}"))
            continue

        # 3) Add to Anki rows
        front = "What is this bird?"
        back = f"{species}"
        anki_rows.append({
            "Front": front,
            "Back": back,
            "Audio": f"[sound:{fname}]",
            "Species": species,
            "ML": f"ML{mlid}",
            "Tags": tags
        })
        time.sleep(args.delay)

    # Write outputs
    out_csv = out_dir / "anki_import.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["Front","Back","Audio","Species","ML","Tags"])
        w.writeheader()
        for r in anki_rows:
            w.writerow(r)

    if errors:
        err_csv = out_dir / "errors.csv"
        with open(err_csv, "w", newline="", encoding="utf-8") as f:
            ew = _csv.writer(f)
            ew.writerow(["ML_ID","Error"])
            ew.writerows(errors)
        print(f"⚠️ {len(errors)} errors logged to {err_csv}")

    print(f"✅ Wrote {len(anki_rows)} notes to {out_csv}")
    print(f"🎧 Media in: {media_dir.resolve()}")
    print("Import into Anki, map fields, and include media (collection.media).")

if __name__ == "__main__":
    main()
