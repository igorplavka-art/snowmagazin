# Snowmagazin Crawler Design

## Goal

Create a standalone crawler project for `snowmagazin.relaxmagazin.sk` that archives the published versions of all available articles without depending on the SkiLoko repository or deployment.

## Scope

The crawler will collect article content and metadata only. Media files are intentionally deferred. Existing Gmail drafts/manuscripts remain a secondary provenance source and are not treated as the canonical published text.

## Architecture

1. Primary discovery and content source: WordPress REST API when available.
2. Fallback discovery: public sitemap/category/archive pages to find article URLs missing from the API.
3. Fallback content source: direct article HTML for URLs not fully represented by the API.
4. Per-article normalized archive written to local output folders.
5. A final CSV manifest and ZIP archive are produced as GitHub Actions artifacts for later upload to the existing Google Drive Snowmagazin archive.

## Article Output

Each article is stored under:

`archive/<year>/<YYYY-MM-DD>-<slug>/`

with:

- `metadata.json` — normalized metadata and provenance
- `published.html` — published article body HTML
- `published.txt` — plain-text rendering of the published article

`metadata.json` includes, when available:

- WordPress post ID
- title
- slug
- canonical/current URL
- published date
- modified date
- author ID/name
- categories/tags
- excerpt
- NextGEN gallery IDs found in content
- referenced media URLs, without downloading them
- source method (`wp_rest` or `html_fallback`)

## Global Manifest

The run produces `articles.csv` with one row per unique article and columns for the normalized metadata, archive path, source method, status, and errors.

Deduplication order:

1. WordPress post ID when available
2. canonical URL
3. normalized URL/slug fallback

## Crawl Behaviour

- Crawl all public posts returned by the WordPress API, paginating until exhausted.
- Discover additional same-site article URLs from public sitemap/archive/category pages.
- Exclude taxonomy, pagination, admin, feed, attachment, search, and non-article URLs.
- Use direct HTML fallback only for URLs not already covered by REST results.
- Preserve the published article body; do not rewrite or editorially improve it.
- Continue on individual failures and record them in the manifest.
- Use conservative request pacing and a descriptive User-Agent.

## GitHub Repository Boundary

The `igorplavka-art/snowmagazin` repository contains only crawler source, tests, workflow configuration, and documentation. Crawled article contents are not committed to git. GitHub Actions stores the crawl output as an artifact.

The SkiLoko repository is not read, modified, imported, or deployed by this project.

## GitHub Actions

A manually runnable workflow will:

1. check out the Snowmagazin repository
2. install Python dependencies
3. run tests
4. run the crawler
5. package `archive/` and `articles.csv` into `snowmagazin-archive.zip`
6. upload the ZIP and CSV as workflow artifacts

## Testing

Unit tests cover:

- NextGEN shortcode extraction
- HTML-to-text normalization
- WordPress REST post normalization
- URL filtering for article candidates
- slug/path normalization
- deduplication
- CSV/archive writing using local fixtures

A smoke crawl mode limits the run to a small number of posts for workflow verification before the full crawl.

## Non-goals for this phase

- downloading images or NextGEN media
- editing/restoring article copy
- comparing drafts against published text
- importing content into SkiLoko
- deploying a public mirror site
