#!/usr/bin/env python3
"""
ML to Anki Audio Downloader

Given a CSV of Macaulay Library asset IDs (ML IDs) and species info,
this script downloads the associated audio files, saves them into a media
folder with clean filenames, and produces an Anki-importable CSV where the
Audio field contains [sound:filename] so Anki will play the clip.

It tries multiple strategies to locate a high-quality downloadable audio URL
from the Macaulay Library asset page. The site's structure can change, so
two robust heuristics are used:
  1) Look for JSON blobs embedded in the HTML that contain .mp3 or .m4a links
  2) As a fallback, search for any direct .mp3/.m4a URLs in the page source

USAGE
-----
1) Prepare an input CSV with columns:
   ML_ID,CommonName,ScientificName,Type,Prompt,Answer,Tags
   - ML_ID: numeric Macaulay Library asset ID (e.g., 123456789)
   - CommonName: e.g., Field Sparrow
   - ScientificName: e.g., Spizella pusilla
   - Type: song, chip, call, flight_call, drum, etc. (optional but recommended)
   - Prompt: what you want on the front of the card (e.g., "Who is this?")
   - Answer: what you want on the back (e.g., "Field Sparrow — song")
   - Tags: space-separated (e.g., "sparrows tn training")

2) Run:
   python ml_to_anki.py --input ./input.csv --out_dir ./out --media_dir ./out/media

3) In Anki:
   - Create a Note Type with fields: Front, Back, Audio, Common, Scientific, Type, ML, Source, Tags
     (or whatever you prefer, just map during import).
   - File > Import > select the generated anki_import.csv
   - Ensure "Fields separated by: Comma" and map columns appropriately.
   - Make sure "Allow HTML in fields" is ON so [sound:...] works.
   - When prompted, include media — place the "media" folder contents into the
     collection.media directory, or import via the dialog.

Dependencies: requests, beautifulsoup4, pandas (for CSV I/O convenience)
"""
import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ML-to-Anki/1.0; +https://example.com)"
}

ASSET_URL_TMPL = "https://macaulaylibrary.org/asset/{mlid}"

def find_audio_url_from_html(html: str) -> Optional[str]:
    """
    Heuristically extract a direct audio URL (.mp3/.m4a) from the asset HTML.
    We search for JSON-like blobs that include 'mp3' or 'm4a' links,
    then fallback to any direct links found in the page text.
    """
    # Common pattern: CDN links ending with .mp3 or .m4a
    # We allow querystrings.
    candidates = re.findall(r'https?://[^\s"\'<>]+?\.(?:mp3|m4a)(?:\?[^\s"\'<>]+)?', html, flags=re.IGNORECASE)
    if candidates:
        # Prefer the longest (often original-quality) or one containing "download" or "audio"
        def score(u: str) -> int:
            s = 0
            s += 5 if "download" in u else 0
            s += 4 if "audio" in u else 0
            s += 3 if "original" in u else 0
            s += len(u) // 50  # rough proxy
            return s
        candidates = sorted(set(candidates), key=score, reverse=True)
        return candidates[0]

    # If nothing, try to parse <audio> tags
    soup = BeautifulSoup(html, "html.parser")
    for audio in soup.find_all("audio"):
        src = audio.get("src")
        if src and (src.lower().endswith(".mp3") or src.lower().endswith(".m4a")):
            return src

    return None

def fetch_audio_url_for_mlid(mlid: str, session: requests.Session) -> Optional[str]:
    """
    Load the asset page and try to discover a downloadable audio URL.
    """
    url = ASSET_URL_TMPL.format(mlid=mlid)
    resp = session.get(url, headers=HEADERS, timeout=25)
    if resp.status_code != 200:
        return None
    return find_audio_url_from_html(resp.text)

def safe_slug(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^\w\-\.\(\) ]+", "", s, flags=re.UNICODE)  # remove odd chars
    s = re.sub(r"\s+", "_", s)
    return s

def build_filename(common: str, vtype: str, mlid: str, ext: str = "mp3") -> str:
    base = f"{common}_{vtype}_ML{mlid}".strip("_")
    return safe_slug(base) + f".{ext}"

def guess_ext_from_url(u: str) -> str:
    u = u.lower()
    if ".m4a" in u:
        return "m4a"
    return "mp3"

def download_file(url: str, out_path: Path, session: requests.Session) -> None:
    with session.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Input CSV with ML_ID and metadata")
    ap.add_argument("--out_dir", required=True, help="Output directory for CSV and logs")
    ap.add_argument("--media_dir", required=True, help="Directory to save audio files")
    ap.add_argument("--delay", type=float, default=0.75, help="Polite delay between requests (sec)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    media_dir = Path(args.media_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.input)
    required_cols = ["ML_ID", "CommonName"]
    for c in required_cols:
        if c not in df.columns:
            sys.exit(f"Missing required column: {c}")

    # Optional columns; create if absent
    for c in ["ScientificName", "Type", "Prompt", "Answer", "Tags"]:
        if c not in df.columns:
            df[c] = ""

    session = requests.Session()

    # Build Anki import rows
    anki_rows = []
    errors = []

    for _, row in df.iterrows():
        mlid = str(row["ML_ID"]).strip()
        common = str(row["CommonName"]).strip()
        scientific = str(row["ScientificName"]).strip()
        vtype = str(row["Type"]).strip() or "call"

        # Either use provided Prompt/Answer or sensible defaults
        prompt = str(row["Prompt"]).strip() or "Who is this?"
        default_answer = f"{common}" + (f" — {vtype}" if vtype else "")
        answer = str(row["Answer"]).strip() or default_answer
        tags = str(row["Tags"]).strip()

        # Find audio URL
        try:
            audio_url = fetch_audio_url_for_mlid(mlid, session=session)
        except Exception as e:
            audio_url = None
            errors.append((mlid, f"fetch error: {e!r}"))

        if not audio_url:
            errors.append((mlid, "no audio URL found"))
            continue

        ext = guess_ext_from_url(audio_url)
        filename = build_filename(common, vtype, mlid, ext)
        out_path = media_dir / filename

        # Download file if not exists
        if not out_path.exists():
            try:
                download_file(audio_url, out_path, session=session)
                time.sleep(args.delay)
            except Exception as e:
                errors.append((mlid, f"download error: {e!r}"))
                continue

        # Anki fields
        # Audio field should include [sound:filename]
        audio_field = f"[sound:{filename}]"
        source = f"ML{mlid}"
        ml_field = f"ML{mlid}"

        anki_rows.append({
            "Front": prompt,
            "Back": answer,
            "Audio": audio_field,
            "Common": common,
            "Scientific": scientific,
            "Type": vtype,
            "ML": ml_field,
            "Source": source,
            "Tags": tags
        })

    # Save Anki CSV
    anki_csv_path = out_dir / "anki_import.csv"
    with open(anki_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Front","Back","Audio","Common","Scientific","Type","ML","Source","Tags"
        ])
        writer.writeheader()
        for r in anki_rows:
            writer.writerow(r)

    # Log errors
    if errors:
        err_path = out_dir / "errors.csv"
        with open(err_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ML_ID","Error"])
            w.writerows(errors)

    print(f"✅ Wrote {len(anki_rows)} rows to {anki_csv_path}")
    if errors:
        print(f"⚠️ {len(errors)} errors logged to {err_path}")
    print(f"🎧 Media saved to: {media_dir.resolve()}")
    print("\nNext steps in Anki:")
    print("1) Create a Note Type with fields: Front, Back, Audio, Common, Scientific, Type, ML, Source, Tags")
    print("2) Import anki_import.csv and map fields; ensure 'Allow HTML in fields' is enabled.")
    print("3) Ensure the media files are available to Anki (place them in the collection.media folder or import with the CSV).")

if __name__ == "__main__":
    main()
