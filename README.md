# Photo Fetcher → Visual Pipeline

This fetcher pulls Macaulay Library **photo ML_IDs** per species for visual ID practice,
then you feed the output (`photos.csv`) into your existing `visual.py` to download files and build Anki CSV.

## Files
- `fetch_photos.py` — reads `fetch_specs.csv`, writes `photos.csv`

## Install
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Input format: `fetch_specs.csv`
Required:
- `Species` — common or scientific name
- `Limit` — how many ML_IDs to sample

Optional:
- `Tags` — space-separated (carried into output)
- `Region` — e.g., `US-TN`, `US`
- `Months` — e.g., `11-02` or `11,12,1`
- `MinRating` — e.g., `3.5` or `4`
- `MaxPerObserver` — e.g., `2`
- `LowQualityFrac` — e.g., `0.3`

### Example
```
Species,Limit,Tags,Region,Months,MinRating,MaxPerObserver,LowQualityFrac
Greater Scaup,15,"Scaup photo winter comparison",US-TN,11-02,3.5,2,0.35
Lesser Scaup,15,"Scaup photo winter comparison",US-TN,11-02,3.5,2,0.35
```

## Run
```bash
# Dry-run just to see counts:
python fetch_photos.py --input fetch_specs.csv --out photos.csv --mode json --pages 5 --seed 42 --dry-run

# Produce photos.csv:
python fetch_photos.py --input fetch_specs.csv --out photos.csv --mode json --pages 5 --seed 42
# (If JSON mode yields nothing, try --mode html)
```

## Next step
Use the output with your existing visual pipeline:
```bash
python visual.py --input photos.csv --out_dir ./out_visual --media_dir ./out_visual/media
```

**Import into Anki** with HTML enabled, make sure images end up in `collection.media`.
