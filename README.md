# Snowmagazin archive crawler

Standalone archival crawler for `https://snowmagazin.relaxmagazin.sk/`.
It is intentionally independent from SkiLoko.

## Article archive

For each discovered published article the crawler stores:

- `metadata.json`
- `published.html`
- `published.txt`
- `articles.csv`

Source priority:

1. WordPress REST API (`content.rendered`) as the canonical published body when available.
2. Sitemap/category/archive discovery for URLs that REST does not expose.
3. Direct article HTML extraction as a fallback.

Drafts and manuscripts from email are intentionally not used as the canonical published copy.

## Media archive

The media crawler preserves the most valuable recoverable assets from published Snowmagazin pages:

- original-size article images where available
- legacy `/wp-content/gallery/...` images
- recoverable NextGEN gallery assets exposed by article pages
- per-file source URL, resolved URL, size and status
- gallery completeness status (`complete`, `partial`, `missing`, `unresolved`)
- a dedicated failure manifest for 404/403/network/non-image failures

Media is written under `media_out/articles/<year>/...` and reconstructed gallery files under `media_out/galleries/<folder>/...`.

## Local use

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m snowmagazin_crawler --output out --limit 10
PYTHONPATH=src python -m snowmagazin_crawler --output out
PYTHONPATH=src python -m snowmagazin_crawler.media --output media_out --limit 10
PYTHONPATH=src python -m snowmagazin_crawler.media --output media_out
```

## GitHub Actions

Workflow modes:

- `smoke` — 10 article crawl
- `full` — complete article crawl
- `media-smoke` — media recovery from 10 posts
- `media-full` — complete media recovery

Generated article/media content is uploaded as GitHub Actions artifacts and is never committed to the repository.
