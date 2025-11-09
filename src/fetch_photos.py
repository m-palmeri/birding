#!/usr/bin/env python3
# See README.md for details. Best run locally with internet access.
from __future__ import annotations
import argparse, csv, random, re, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

UA = "Mozilla/5.0 (compatible; BirdID-Fetcher/1.0; +https://example.org)"
HEADERS = {"User-Agent": UA}

def parse_months_field(s: str) -> Optional[List[int]]:
    if not s or str(s).strip() == "":
        return None
    s = str(s).strip()
    if "-" in s and "," not in s:
        a, b = s.split("-", 1)
        a = int(a); b = int(b)
        if a <= b:
            return list(range(a, b + 1))
        return list(range(a, 13)) + list(range(1, b + 1))
    vals = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok: continue
        try: vals.append(int(tok))
        except: pass
    vals = [v for v in vals if 1 <= v <= 12]
    return vals or None

@dataclass
class Candidate:
    mlid: str
    rating: Optional[float]
    observer: Optional[str]
    region: Optional[str]
    date: Optional[str]
    month: Optional[int]
    quality_rank: Optional[int]
    href: Optional[str]

def polite_get(url: str, params: Optional[Dict[str, Any]] = None, delay: float = 0.7, timeout: int = 30) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, headers={"User-Agent": UA}, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp

def fetch_json_candidates(species: str, pages: int = 3) -> List[Candidate]:
    cands: List[Candidate] = []
    base = "https://search.macaulaylibrary.org/catalog.json"
    for page in range(1, pages + 1):
        params = {"mediaType":"photo","q":species,"sort":"rating_rank_desc","page":page}
        try:
            r = polite_get(base, params=params)
            data = r.json()
        except Exception:
            break
        items = data.get("results") or data.get("data") or []
        for it in items:
            asset_id = str(it.get("assetId") or it.get("id") or "").strip()
            if not asset_id: continue
            rating = it.get("rating")
            try: rating = float(rating) if rating is not None else None
            except: rating = None
            user = it.get("userDisplayName") or it.get("user") or None
            region = it.get("regionCode") or it.get("subnational1Code") or it.get("countryCode") or None
            date_txt = it.get("observedOn") or it.get("date") or None
            month = None
            if date_txt:
                try: month = dateparser.parse(date_txt).month
                except Exception: month = None
            href = it.get("href") or it.get("assetPage") or None
            cands.append(Candidate(asset_id, rating, user, region, date_txt, month, it.get("rank") if isinstance(it.get("rank"), int) else None, href))
    return cands

def fetch_html_candidates(species: str, pages: int = 3) -> List[Candidate]:
    cands: List[Candidate] = []
    base = "https://search.macaulaylibrary.org/catalog"
    for page in range(1, pages + 1):
        params = {"mediaType":"photo","q":species,"sort":"rating_rank_desc","page":page}
        try:
            r = polite_get(base, params=params)
        except Exception:
            break
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a[href*='/asset/']"):
            href = a.get("href","")
            m = re.search(r"/asset/(\d+)", href)
            if not m: continue
            asset_id = m.group(1)
            rating = None
            rating_el = a.find_next(string=re.compile(r"(\d(\.\d)?)\s*stars", re.I))
            if rating_el:
                try: rating = float(re.search(r"(\d(\.\d)?)", rating_el).group(1))
                except: rating = None
            card = a.find_parent()
            user, date_txt, region = None, None, None
            if card:
                txt = card.get_text(" ", strip=True)
                dm = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
                if dm: date_txt = dm.group(1)
                um = re.search(r"by\s+([A-Za-z0-9 .'-]+)", txt)
                if um: user = um.group(1)
            month = None
            if date_txt:
                try: month = dateparser.parse(date_txt).month
                except Exception: month = None
            cands.append(Candidate(asset_id, rating, user, region, date_txt, month, None, href))
    return cands

def stratified_sample(cands: List[Candidate], limit: int, min_rating: float, max_per_observer: int, months: Optional[List[int]], region: Optional[str], low_quality_frac: float, rng: random.Random) -> List[Candidate]:
    def ok_region(c: Candidate) -> bool:
        if not region: return True
        if not c.region: return True
        return region.lower() in c.region.lower()
    def ok_month(c: Candidate) -> bool:
        if not months: return True
        if c.month is None: return True
        return c.month in months
    filtered = [c for c in cands if (c.rating is None or c.rating >= min_rating) and ok_region(c) and ok_month(c)]
    seen, deduped = set(), []
    for c in filtered:
        if c.mlid in seen: continue
        seen.add(c.mlid); deduped.append(c)
    counts, capped = {}, []
    for c in deduped:
        obs = c.observer or "_unknown_"
        n = counts.get(obs, 0)
        if n < max_per_observer:
            capped.append(c); counts[obs] = n + 1
    if not capped: return []
    with_rating = [c for c in capped if c.rating is not None]
    no_rating = [c for c in capped if c.rating is None]
    with_rating.sort(key=lambda x: (-x.rating, x.quality_rank or 999999))
    top_cut = max(1, int(round(limit * (1 - low_quality_frac))))
    top_pool = with_rating[: max(top_cut * 3, top_cut + 5)]
    rng.shuffle(top_pool)
    top_pick = top_pool[: min(len(top_pool), top_cut)]
    realistic_pool = with_rating[len(top_pool):] + no_rating
    rng.shuffle(realistic_pool)
    realistic_need = max(0, limit - len(top_pick))
    realistic_pick = realistic_pool[: realistic_need]
    picks = top_pick + realistic_pick
    rng.shuffle(picks)
    return picks[:limit]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="fetch_specs.csv")
    ap.add_argument("--out", default="photos.csv", help="Output CSV for visual.py")
    ap.add_argument("--mode", choices=["json","html"], default="json")
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-rating", type=float, default=None)
    ap.add_argument("--max-per-observer", type=int, default=None)
    ap.add_argument("--low-quality-frac", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import pandas as pd
    df = pd.read_csv(args.input)
    for c in ["Species","Limit"]:
        if c not in df.columns:
            raise SystemExit(f"Missing required column: {c}")
    for c in ["Tags","Region","Months","MinRating","MaxPerObserver","LowQualityFrac"]:
        if c not in df.columns:
            df[c] = ""

    rng = random.Random(args.seed)
    out_rows = []

    for _, row in df.iterrows():
        species = str(row["Species"]).strip()
        limit = int(row["Limit"])
        tags = str(row["Tags"]).strip()
        region = str(row["Region"]).strip() or None
        months = parse_months_field(str(row["Months"]).strip()) if str(row["Months"]).strip() else None
        min_rating = args.min_rating if args.min_rating is not None else (float(row["MinRating"]) if str(row["MinRating"]).strip() else 3.5)
        max_per_obs = args.max_per_observer if args.max_per_observer is not None else (int(row["MaxPerObserver"]) if str(row["MaxPerObserver"]).strip() else 2)
        lowq_frac = args.low_quality_frac if args.low_quality_frac is not None else (float(row["LowQualityFrac"]) if str(row["LowQualityFrac"]).strip() else 0.3)

        if args.mode == "json":
            cands = fetch_json_candidates(species, pages=args.pages)
            if not cands:
                cands = fetch_html_candidates(species, pages=args.pages)
        else:
            cands = fetch_html_candidates(species, pages=args.pages)

        picks = stratified_sample(cands, limit, min_rating, max_per_obs, months, region, lowq_frac, rng)

        if args.dry_run:
            print(f"{species}: gathered={len(cands)} picks={len(picks)}")
            continue

        for c in picks:
            out_rows.append({"ML_ID": c.mlid, "Species": species, "Tags": tags})

    if args.dry_run:
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ML_ID","Species","Tags"])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    print(f"✅ Wrote {len(out_rows)} rows to {out_path}")

if __name__ == "__main__":
    main()
