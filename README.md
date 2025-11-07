# birding

Small utility to download Macaulay Library audio assets and produce an Anki-importable CSV with media.

Getting started
---------------

1) Create and activate a Python virtual environment (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install Python dependencies from `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3) (Optional) Install `ffmpeg` if you want the script to trim audio clips:

macOS (Homebrew):

```bash
brew install ffmpeg
```

What the script expects
-----------------------

Input CSV columns (headers) supported:

- `ML_ID` (required) — Macaulay Library asset ID
- `CommonName` (required)
- `Type` (optional) — e.g. song, call
- `Tags` (optional) — space-separated tags for Anki (e.g. `sparrows tn training`)
- `ClipStart` (optional) — start time in seconds or mm:ss or hh:mm:ss
- `ClipEnd` (optional) — end time in seconds or mm:ss or hh:mm:ss
- `MaxClipSeconds` (optional) — caps final clip length (defaults to 10s when trimming)

Notes:
- The presence of any of `ClipStart`, `ClipEnd`, or `MaxClipSeconds` triggers trimming for that row. If none are present, the downloaded audio is left intact.
- `Prompt` and `Answer` columns are not required — the script uses a fixed prompt `What is this?` and generates the answer as `CommonName - Type`.

Usage
-----

```bash
python3 src/audio-download.py --input ./input.csv --out_dir ./out --media_dir ./out/media
```

Outputs
-------
- `out/anki_import.csv` — CSV ready to import into Anki
- `out/media/` — downloaded (and optionally trimmed) audio files
- `out/errors.csv` — any fetch/download/trim errors

Troubleshooting
---------------

- If you see `ModuleNotFoundError: No module named 'requests'` or similar, make sure you installed dependencies in the active environment:

```bash
python -m pip install -r requirements.txt
```

- If trimming is not working, ensure `ffmpeg` is installed and in your PATH.

License
-------

This repository contains small utilities for personal study; check Macaulay Library terms before redistributing downloaded media.
# birding
