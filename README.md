# Playwright Photo Fetcher

Collect Macaulay Library client-rendered photo ML_IDs using Playwright and produce `photos.csv` for `visual.py`.

## Install
pip install -r requirements.txt
python -m playwright install chromium

## Input CSV (fetch_specs.csv)
Required: Species, TaxonCode, Limit
Optional: Tags, QueryParams (appended to the catalog URL)

## Run
python fetch_playwright.py --input fetch_specs.csv --out photos.csv --pages 10 --seed 42
python fetch_playwright.py --input fetch_specs.csv --out photos.csv --pages 5 --headful --slowmo 1000
