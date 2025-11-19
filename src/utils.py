#!/usr/bin/env python3
from __future__ import annotations
import re, time, math
from pathlib import Path
from typing import Optional
import requests

HEADERS = {"User-Agent": "ML-Asset-Downloader/1.0"}
CDN_TMPL = "https://cdn.download.ams.birds.cornell.edu/api/v1/asset/{mlid}"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def clean_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^\w\-\.\(\) ]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s

def parse_time_to_ms(s: str | float | int | None) -> Optional[int]:
    if s is None: return None
    if isinstance(s, float) and math.isnan(s):
        return None
    if isinstance(s, (int, float)): return int(float(s) * 1000)
    s = str(s).strip()
    if not s: return None
    try:
        if ":" not in s:
            return int(float(s) * 1000)
        parts = [p.strip() for p in s.split(":")]
        if len(parts) == 2:
            mm, ss = parts
            return int((int(mm)*60 + float(ss)) * 1000)
        if len(parts) == 3:
            hh, mm, ss = parts
            return int(((int(hh)*3600)+(int(mm)*60)+float(ss)) * 1000)
        return None
    except Exception:
        return None

def infer_extension_from_headers(resp: requests.Response) -> str:
    ctype = resp.headers.get("Content-Type","").lower()
    if "m4a" in ctype or "mp4" in ctype: return ".m4a"
    if "mpeg" in ctype or "mp3" in ctype: return ".mp3"
    if "wav" in ctype: return ".wav"
    if "jpeg" in ctype or "jpg" in ctype: return ".jpg"
    if "png" in ctype: return ".png"
    if "webp" in ctype: return ".webp"
    return ".mp3"

def build_filename(species: str, mlid: str, ext: str, suffix: str | None = None) -> str:
    base = f"{species}_ML{mlid}"
    if suffix:
        base += f"_{suffix}"
    return clean_name(base) + ext

def download_asset(mlid: str, out_path: Path, session: requests.Session | None = None, delay: float = 0.5) -> str:
    session = session or requests.Session()
    url = CDN_TMPL.format(mlid=str(mlid).strip())
    r = session.get(url, headers=HEADERS, stream=True, timeout=60)
    r.raise_for_status()
    ext = infer_extension_from_headers(r)
    final_path = out_path.with_suffix(ext)
    with open(final_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk: f.write(chunk)
    time.sleep(delay)
    return str(final_path)
