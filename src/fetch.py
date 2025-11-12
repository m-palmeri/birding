#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, json, random, re, sys, time
from pathlib import Path
from typing import Set, List

import pandas as pd
from playwright.async_api import async_playwright
import traceback

CATALOG_BASE = "https://media.ebird.org/catalog"
ASSET_ID_RE = re.compile(r"/asset/(\d+)")

def build_catalog_url(taxon_code: str) -> str:
    base = f"https://media.ebird.org/catalog?taxonCode={taxon_code}&mediaType=photo&view=grid&sort=rating_rank_desc"
    # initial cache-buster
    base += f"&_cb={int(time.time()*1000)}"
    return base

ASSET_ID_RE = re.compile(r"/asset/(\d+)")

async def collect_ids_from_page(page) -> set[str]:
    ids: set[str] = set()

    # Anchors with /asset/<id>
    anchors = await page.locator("a[href*='/asset/']").all()
    for a in anchors:
        href = await a.get_attribute("href")
        if not href:
            continue
        m = ASSET_ID_RE.search(href)
        if m:
            ids.add(m.group(1))

    # Any element with data-asset-id
    data_nodes = await page.locator("[data-asset-id]").all()
    for el in data_nodes:
        aid = await el.get_attribute("data-asset-id")
        if aid and aid.isdigit():
            ids.add(aid)

    return ids

async def first_asset_id(page) -> str | None:
    a = page.locator("a[href*='/asset/']").first
    if await a.count():
        href = await a.get_attribute("href")
        if href:
            m = ASSET_ID_RE.search(href)
            if m:
                return m.group(1)
    el = page.locator("[data-asset-id]").first
    if await el.count():
        aid = await el.get_attribute("data-asset-id")
        if aid and aid.isdigit():
            return aid
    return None

async def dom_asset_ids(page) -> Set[str]:
    # Grab IDs via a single DOM eval (fast)
    ids = await page.evaluate("""
    () => {
      const out = new Set();
      for (const a of document.querySelectorAll("a[href*='/asset/']")) {
        const m = a.getAttribute('href')?.match(/\\/asset\\/(\\d+)/);
        if (m) out.add(m[1]);
      }
      for (const el of document.querySelectorAll("[data-asset-id]")) {
        const v = el.getAttribute("data-asset-id");
        if (v && /^\\d+$/.test(v)) out.add(v);
      }
      return Array.from(out);
    }""")
    return set(ids)

async def wait_for_grid(page, timeout_ms: int):
    # first paint of any asset
    try:
        await page.wait_for_selector("a[href*='/asset/'], [data-asset-id]", timeout=int(timeout_ms))
    except:
        pass

async def wait_for_growth(page, prev_count: int, timeout_ms: int) -> bool:
    # poll until count increases or timeout
    end = page.context._loop.time() + (timeout_ms / 1000.0)
    while page.context._loop.time() < end:
        cur = await dom_asset_ids(page)
        if len(cur) > prev_count:
            return True
        await page.wait_for_timeout(200)
    return False

async def load_more_until_done(
    page,
    timeout_ms: int,
    max_clicks: int = 20,
    target_min_ids: Optional[int] = None
) -> Set[str]:
    ids = await dom_asset_ids(page)
    clicks = 0

    while True:
        if target_min_ids and len(ids) >= target_min_ids:
            break
        if clicks >= max_clicks:
            break

        # Try common "More" selectors
        btn = page.get_by_role("button", name=re.compile(r"(more|show|load)", re.I)).first
        if not await btn.count():
            # fallback: text match on button or link
            btn = page.locator("button:has-text('More'), a:has-text('More'), button:has-text('Show'), a:has-text('Show')").first

        if await btn.count():
            try:
                await btn.scroll_into_view_if_needed()
                before = len(ids)
                await btn.click()
                # give the SPA time to fetch & render
                await page.wait_for_load_state("networkidle", timeout=int(timeout_ms))
                grew = await wait_for_growth(page, before, timeout_ms=int(timeout_ms))
                ids = await dom_asset_ids(page)
                clicks += 1
                if not grew:
                    # stop if clicking didn't add anything
                    break
                continue
            except Exception:
                # fall through to scroll
                pass

        # No button? try infinite scroll
        before = len(ids)
        await page.evaluate("""() => { window.scrollTo(0, document.body.scrollHeight); }""")
        await page.wait_for_timeout(800)
        await page.wait_for_load_state("networkidle", timeout=int(timeout_ms))
        grew = await wait_for_growth(page, before, timeout_ms=int(timeout_ms))
        ids = await dom_asset_ids(page)
        if not grew:
            break

    return ids

async def gather_for_taxon(
    play,
    taxon_code: str,
    pages: int,                # you can keep passing this; we’ll translate to a click count
    headful: bool,
    slowmo: int,
    timeout_ms: int
) -> list[str]:
    # Treat `pages` as a rough proxy for "how deep to load"; tune 2x if needed
    max_clicks = max(3, pages)          # e.g., pages=10 -> up to 10 "More" clicks
    target_min_ids = pages * 30         # rough expectation (~30/thumb page); adjust if you see diff

    browser = await play.chromium.launch(headless=not headful, slow_mo=int(slowmo or 0))
    context = await browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/118.0 Safari/537.36")
    )
    page = await context.new_page()

    try:
        url = build_catalog_url(taxon_code)
        await page.goto(str(url))
        await page.wait_for_load_state("domcontentloaded", timeout=int(timeout_ms))
        await wait_for_grid(page, timeout_ms=int(timeout_ms))
        # Start count
        ids = await dom_asset_ids(page)
        print(f"[INIT] {taxon_code}: {len(ids)} ids")

        # Load more in a loop
        ids = await load_more_until_done(
            page,
            timeout_ms=int(timeout_ms),
            max_clicks=int(max_clicks),
            target_min_ids=int(target_min_ids)
        )

        print(f"[DONE] {taxon_code}: {len(ids)} unique ids")
        return list(ids)

    finally:
        await context.close()
        await browser.close()

def load_cache(cache_dir: Path, code: str) -> Set[str]:
    p = cache_dir / f"{code}.json"
    if p.exists():
        try:
            return set(str(x) for x in json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_cache(cache_dir: Path, code: str, ids: Set[str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{code}.json").write_text(json.dumps(sorted(list(ids))), encoding="utf-8")

def sample_ids(all_ids: List[str], k: int, rng: random.Random) -> List[str]:
    if k >= len(all_ids): return list(all_ids)
    return rng.sample(all_ids, k)

async def main_async(args) -> int:
    df = pd.read_csv(args.input)
    for c in ["Species","TaxonCode","Limit"]:
        if c not in df.columns:
            print(f"Missing required column: {c}", file=sys.stderr)
            return 2
    if "Tags" not in df.columns: df["Tags"] = ""
    if "QueryParams" not in df.columns: df["QueryParams"] = ""
    out_rows = []
    cache_dir = Path(args.cache_dir)
    rng = random.Random(args.seed)
    async with async_playwright() as play:
        for _, row in df.iterrows():
            species = str(row["Species"]).strip()
            code = str(row["TaxonCode"]).strip()
            limit = int(row["Limit"])
            tags = str(row["Tags"]).strip()
            print(f"\n== {species} ({code}) pages={args.pages} limit={limit} ==")
            cached = load_cache(cache_dir, code)
            print(f"Cache has {len(cached)} ids")
            fresh_ids = await gather_for_taxon(play, code, args.pages, args.headful, args.slowmo, args.timeout)
            print(f"Fetched {len(fresh_ids)} ids this run")
            all_ids = cached.union(set(fresh_ids))
            print(f"Total pooled ids = {len(all_ids)}")
            if not all_ids:
                print("No IDs found; skipping.")
                continue
            picks = sample_ids(list(all_ids), limit, rng)
            for mlid in picks:
                out_rows.append({"ML_ID": mlid, "Species": species, "Tags": tags})
            save_cache(cache_dir, code, all_ids)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["ML_ID","Species","Tags"])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"\n✅ Wrote {len(out_rows)} rows to {out_path}")
    return 0

def build_argparser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="photos.csv")
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--cache-dir", default="./.cache_mlac_ids")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--slowmo", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=int, default=15000, help="ms")
    return ap

def main():
    ap = build_argparser()
    args = ap.parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted."); rc = 130
    sys.exit(rc)

if __name__ == "__main__":
    main()
