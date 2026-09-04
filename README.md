# Snowmagazin archive crawler

Standalone archival crawler for `https://snowmagazin.relaxmagazin.sk/`.
It is intentionally independent from SkiLoko.

## What it stores

For each discovered published article:

- `metadata.json`
- `published.html`
- `published.txt`

The run also creates `articles.csv`. Media URLs and legacy NextGEN gallery IDs are inventoried, but media files are not downloaded in this phase.

## Source priority

1. WordPress REST API (`content.rendered`) as the canonical published body when available.
2. Sitemap/category/archive discovery for URLs that REST does not expose.
3. Direct article HTML extraction as a fallback.

Drafts and manuscripts from email are intentionally not used as the canonical published copy.

## Local use

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m snowmagazin_crawler --output out --limit 10
PYTHONPATH=src python -m snowmagazin_crawler --output out
```

## GitHub Actions

- Pushes to `crawler-v1` run tests and a 10-article smoke crawl.
- Pushes to `main` run tests and a full crawl.
- `workflow_dispatch` is also enabled; on `main` it runs full, on other branches smoke.
- Generated archive content is uploaded as a GitHub Actions artifact and is never committed to the repository.

Artifacts:

- `snowmagazin-archive.zip`
- `out/articles.csv`
