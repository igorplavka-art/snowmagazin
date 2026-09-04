# Snowmagazin Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone crawler that archives all publicly available published Snowmagazin articles into normalized files and produces CSV/ZIP artifacts.

**Architecture:** Use WordPress REST as the primary structured source, public archive/sitemap discovery as a fallback, and direct article HTML as a secondary content fallback. Normalize each article into metadata, HTML, and plain text, then package everything through GitHub Actions without committing crawled content.

**Tech Stack:** Python 3.12, requests, BeautifulSoup4, pytest, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-04-snowmagazin-crawler-design.md`

## Global Constraints

- Repository is completely separate from SkiLoko.
- Crawled article contents must not be committed to git.
- Published website content is canonical; Gmail drafts are out of scope for crawler output.
- Media URLs may be inventoried, but media files are not downloaded in this phase.
- Individual crawl failures must not abort the whole run.

---

### Task 1: Core parsing and normalization

**Files:**
- Create: `src/snowmagazin_crawler/core.py`
- Create: `tests/test_core.py`

**Interfaces:**
- Produces: `extract_gallery_ids(html)`, `html_to_text(html)`, `safe_slug(value)`, `normalize_wp_post(post)`, `is_article_url(url)`

- [ ] **Step 1:** Write failing tests for gallery IDs, plain text, slug normalization, REST normalization, and URL filtering.
- [ ] **Step 2:** Run `PYTHONPATH=src pytest tests/test_core.py -v`; expect import/function failures.
- [ ] **Step 3:** Implement the minimal functions in `core.py`.
- [ ] **Step 4:** Re-run the core tests; expect all pass.
- [ ] **Step 5:** Commit core parser and tests.

### Task 2: REST and fallback discovery

**Files:**
- Create: `src/snowmagazin_crawler/discovery.py`
- Create: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `is_article_url(url)`
- Produces: `iter_wp_posts(session, base_url, limit=None)`, `discover_article_urls(session, base_url, max_pages=None)`

- [ ] **Step 1:** Write failing tests with fake response/session fixtures for REST pagination and archive-link discovery.
- [ ] **Step 2:** Run `PYTHONPATH=src pytest tests/test_discovery.py -v`; expect failures due to missing implementation.
- [ ] **Step 3:** Implement REST pagination using `/wp-json/wp/v2/posts?per_page=100&page=N` with graceful termination.
- [ ] **Step 4:** Implement sitemap/archive discovery and same-site article filtering.
- [ ] **Step 5:** Re-run discovery tests; expect all pass.
- [ ] **Step 6:** Commit discovery logic and tests.

### Task 3: Archive writer and deduplication

**Files:**
- Create: `src/snowmagazin_crawler/archive.py`
- Create: `tests/test_archive.py`

**Interfaces:**
- Produces: `article_key(article)`, `write_article(article, output_dir)`, `write_manifest(rows, csv_path)`

- [ ] **Step 1:** Write failing tests for keys, paths, article files, and CSV output.
- [ ] **Step 2:** Run `PYTHONPATH=src pytest tests/test_archive.py -v`; expect failures.
- [ ] **Step 3:** Implement deterministic archive paths and UTF-8 writers.
- [ ] **Step 4:** Re-run archive tests; expect all pass.
- [ ] **Step 5:** Commit archive writer and tests.

### Task 4: Crawler orchestration and fallback fetch

**Files:**
- Create: `src/snowmagazin_crawler/crawler.py`
- Create: `src/snowmagazin_crawler/__main__.py`
- Create: `tests/test_crawler.py`

**Interfaces:**
- Consumes: discovery/core/archive functions
- Produces: CLI `python -m snowmagazin_crawler --output out [--limit N]`

- [ ] **Step 1:** Write a failing orchestration test proving REST posts archive, duplicates skip, fallback URLs fetch, and errors become manifest rows.
- [ ] **Step 2:** Run the crawler test; expect failure.
- [ ] **Step 3:** Implement orchestration with User-Agent, timeout, pacing, and per-article error capture.
- [ ] **Step 4:** Implement direct HTML fallback extraction for title/date/body/canonical URL.
- [ ] **Step 5:** Run the full suite; expect all tests pass.
- [ ] **Step 6:** Commit crawler CLI and orchestration.

### Task 5: Packaging and GitHub Actions

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.github/workflows/crawl.yml`
- Create: `README.md`

**Interfaces:**
- Branch push artifact: smoke crawl limited to 10 articles
- Main push artifact: full crawl
- Artifact outputs: `articles.csv`, `snowmagazin-archive.zip`

- [ ] **Step 1:** Add `requests`, `beautifulsoup4`, and `pytest` dependencies.
- [ ] **Step 2:** Ignore generated archives, ZIPs, caches, and virtual environments.
- [ ] **Step 3:** Add a workflow that tests first, performs a 10-article smoke crawl on non-main pushes, performs a full crawl on main, zips the output, and uploads artifacts.
- [ ] **Step 4:** Document local and CI usage in README.
- [ ] **Step 5:** Run `PYTHONPATH=src pytest -q` and `PYTHONPATH=src python -m snowmagazin_crawler --help`.
- [ ] **Step 6:** Commit workflow and packaging.

### Task 6: Remote smoke and full crawl verification

**Files:**
- No new files unless verification exposes a bug.

- [ ] **Step 1:** Push `crawler-v1`; inspect the smoke workflow.
- [ ] **Step 2:** Verify the smoke artifact contains non-empty article files and a sensible CSV.
- [ ] **Step 3:** Merge to `main`, automatically triggering a full crawl.
- [ ] **Step 4:** Download the full artifact and verify counts, errors, and non-empty published files.
- [ ] **Step 5:** Upload the full archive artifact into the existing Google Drive Snowmagazin archive folder.
