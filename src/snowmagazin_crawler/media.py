import argparse
import csv
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .core import normalize_wp_post, safe_slug
from .discovery import iter_wp_posts

BASE_URL = 'https://snowmagazin.relaxmagazin.sk'
USER_AGENT = 'SnowmagazinMediaArchive/1.0 (+historical preservation; repository owner)'
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
LEGACY_HOSTS = {
    'snowmagazin.sk', 'www.snowmagazin.sk',
    'snowmagazin.relaxmagazin.sk', 'relaxmagazin.sk', 'www.relaxmagazin.sk',
}
CONTENT_SELECTORS = (
    '.tag-styles', '.entry-content', '.post-content', '.td-post-content',
    '.article-content', '.single-post-content', '.post-entry', 'article .content',
)
GALLERY_RE = re.compile(r'https?://[^\"\'<>\s]+/wp-content/gallery/[^\"\'<>\s]+', re.I)
WP_GALLERY_PATH_RE = re.compile(r'/wp-content/gallery/([^/]+)/', re.I)
SIZE_SUFFIX_RE = re.compile(r'-(?:\d{2,5})x(?:\d{2,5})(?=\.(?:jpe?g|png|gif|webp)$)', re.I)


def _clean_url(url):
    if not url:
        return ''
    url = url.strip().replace('&amp;', '&')
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', parsed.query, ''))


def _mirror_url(url, base_url):
    parsed = urlparse(url)
    if '/wp-content/' not in parsed.path or parsed.netloc.lower() not in LEGACY_HOSTS:
        return url
    base = urlparse(base_url)
    return urlunparse((base.scheme, base.netloc, parsed.path, '', parsed.query, ''))


def _original_size_url(url):
    parsed = urlparse(url)
    path = SIZE_SUFFIX_RE.sub('', parsed.path)
    # NextGEN thumbnails commonly live under /thumbs/thumbs_<name>.
    path = re.sub(r'/thumbs/thumbs_', '/', path, flags=re.I)
    return urlunparse((parsed.scheme, parsed.netloc, path, '', parsed.query, ''))


def media_candidates(url, base_url=BASE_URL):
    url = _clean_url(url)
    if not url:
        return []
    mirrored = _mirror_url(url, base_url)
    candidates = []
    for candidate in (
        _original_size_url(mirrored), mirrored,
        _original_size_url(url), url,
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _add_media_url(found, seen, raw_url, page_url):
    if not raw_url or not isinstance(raw_url, str):
        return
    raw_url = raw_url.strip()
    if not raw_url or raw_url.startswith(('data:', 'javascript:', '#')):
        return
    url = _clean_url(urljoin(page_url, raw_url))
    path = urlparse(url).path.lower()
    if not any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return
    if url not in seen:
        seen.add(url)
        found.append(url)


def extract_page_media(page_html, page_url):
    soup = BeautifulSoup(page_html or '', 'html.parser')
    root = None
    for selector in CONTENT_SELECTORS:
        root = soup.select_one(selector)
        if root:
            break
    if root is None:
        root = soup.find('article')
    if root is None:
        root = soup

    urls = []
    seen = set()
    for tag in root.find_all(True):
        for attr in ('src', 'href', 'data-src', 'data-lazy-src', 'data-full-url', 'data-image'):
            _add_media_url(urls, seen, tag.get(attr), page_url)
        for attr in ('srcset', 'data-srcset'):
            srcset = tag.get(attr)
            if not srcset:
                continue
            for part in srcset.split(','):
                _add_media_url(urls, seen, part.strip().split(' ')[0], page_url)

    # NextGEN can serialize full image URLs in script/data blocks outside the visual body.
    for match in GALLERY_RE.findall(page_html or ''):
        _add_media_url(urls, seen, match, page_url)
    for match in re.findall(r'[\"\']([^\"\']*/wp-content/gallery/[^\"\']+\.(?:jpe?g|png|gif|webp)(?:\?[^\"\']*)?)[\"\']', page_html or '', re.I):
        _add_media_url(urls, seen, match, page_url)

    folders = []
    for url in urls:
        match = WP_GALLERY_PATH_RE.search(urlparse(url).path)
        if match and match.group(1) not in folders:
            folders.append(match.group(1))
    return {'urls': urls, 'gallery_folders': folders}


def _looks_like_image(content, content_type=''):
    if not content:
        return False
    ctype = (content_type or '').lower()
    if ctype.startswith('image/'):
        return True
    return (
        content.startswith(b'\xff\xd8\xff')
        or content.startswith(b'\x89PNG\r\n\x1a\n')
        or content.startswith((b'GIF87a', b'GIF89a'))
        or (len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP')
    )


def download_media(session, source_url, destination, base_url=BASE_URL, retries=2):
    destination = Path(destination)
    last_error = ''
    attempted = []
    for candidate in media_candidates(source_url, base_url):
        for attempt in range(retries + 1):
            attempted.append(candidate)
            try:
                response = session.get(candidate, timeout=35, allow_redirects=True)
                status = getattr(response, 'status_code', 0)
                if status >= 400:
                    last_error = f'HTTP {status}'
                    break
                content = getattr(response, 'content', b'') or b''
                ctype = (getattr(response, 'headers', {}) or {}).get('Content-Type', '')
                if not _looks_like_image(content, ctype):
                    last_error = f'not-image content-type={ctype or "unknown"}'
                    break
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                return {
                    'status': 'ok', 'source_url': source_url, 'resolved_url': candidate,
                    'path': str(destination), 'bytes': len(content), 'error': '',
                    'attempts': len(attempted),
                }
            except Exception as exc:
                last_error = f'{type(exc).__name__}: {exc}'
                if attempt < retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                break
    return {
        'status': 'error', 'source_url': source_url, 'resolved_url': '',
        'path': str(destination), 'bytes': 0, 'error': last_error,
        'attempts': len(attempted),
    }


def _filename_for_url(url):
    name = unquote(Path(urlparse(url).path).name) or 'image.jpg'
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    if len(name) > 180:
        stem = Path(name).stem[:140]
        suffix = Path(name).suffix[:12]
        name = stem + '-' + hashlib.sha1(url.encode()).hexdigest()[:10] + suffix
    return name


def _gallery_folder(url):
    match = WP_GALLERY_PATH_RE.search(urlparse(url).path)
    return match.group(1) if match else ''


def _destination_for(article, url, output_dir):
    folder = _gallery_folder(url)
    filename = _filename_for_url(_original_size_url(url))
    if folder:
        return Path(output_dir) / 'galleries' / safe_slug(folder) / filename
    year = str(article.get('published_date') or '')[:4]
    if not year.isdigit():
        year = 'unknown'
    return Path(output_dir) / 'articles' / year / safe_slug(article.get('slug') or article.get('title')) / filename


def summarize_gallery(article_url, gallery_ids, folders, media_results):
    downloaded = sum(1 for item in media_results if item.get('status') == 'ok')
    failed = sum(1 for item in media_results if item.get('status') != 'ok')
    if failed and downloaded:
        status = 'partial'
    elif failed:
        status = 'missing'
    elif downloaded:
        status = 'complete'
    else:
        status = 'unresolved'
    return {
        'article_url': article_url,
        'gallery_ids': ';'.join(str(x) for x in gallery_ids or []),
        'gallery_folders': ';'.join(folders or []),
        'downloaded_count': downloaded,
        'failed_count': failed,
        'status': status,
    }


def _write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})


def crawl_media(base_url=BASE_URL, output_dir='media_out', limit=None, workers=6):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'text/html,image/*;q=0.9,*/*;q=0.5'})

    articles = []
    for item in iter_wp_posts(session, base_url, limit=limit):
        try:
            articles.append(normalize_wp_post(item))
        except Exception:
            continue

    media_jobs = {}
    article_gallery_context = []
    page_failures = []

    for article in articles:
        page_url = article.get('url') or ''
        urls = list(article.get('media_urls') or [])
        folders = []
        try:
            response = session.get(page_url, timeout=35, allow_redirects=True)
            if getattr(response, 'status_code', 0) >= 400:
                raise RuntimeError(f'HTTP {response.status_code}')
            page_media = extract_page_media(getattr(response, 'text', '') or '', page_url)
            for url in page_media['urls']:
                if url not in urls:
                    urls.append(url)
            folders = page_media['gallery_folders']
        except Exception as exc:
            page_failures.append({
                'kind': 'article_page', 'article_url': page_url, 'url': page_url,
                'status': 'error', 'error': f'{type(exc).__name__}: {exc}',
            })

        article_gallery_context.append({
            'article_url': page_url,
            'gallery_ids': article.get('nggallery_ids') or [],
            'folders': folders,
            'urls': urls,
        })
        for url in urls:
            parsed = urlparse(url)
            if not parsed.scheme.startswith('http'):
                continue
            key = _original_size_url(_mirror_url(_clean_url(url), base_url))
            if key not in media_jobs:
                media_jobs[key] = {'article': article, 'url': url}

    results = []
    def do_job(job):
        article = job['article']
        url = job['url']
        destination = _destination_for(article, url, output_dir)
        local_session = requests.Session()
        local_session.headers.update(session.headers)
        result = download_media(local_session, url, destination, base_url=base_url)
        result.update({
            'article_url': article.get('url') or '',
            'article_title': article.get('title') or '',
            'year': str(article.get('published_date') or '')[:4],
            'gallery_folder': _gallery_folder(url),
        })
        return result

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(do_job, job) for job in media_jobs.values()]
        for future in as_completed(futures):
            results.append(future.result())

    by_article = {}
    for result in results:
        by_article.setdefault(result.get('article_url'), []).append(result)

    gallery_rows = []
    for context in article_gallery_context:
        if not context['gallery_ids'] and not context['folders']:
            continue
        gallery_results = [
            r for r in by_article.get(context['article_url'], [])
            if r.get('gallery_folder') or context['gallery_ids']
        ]
        gallery_rows.append(summarize_gallery(
            context['article_url'], context['gallery_ids'], context['folders'], gallery_results
        ))

    failures = page_failures + [
        {'kind': 'media_file', 'article_url': r.get('article_url', ''), 'url': r.get('source_url', ''),
         'status': 'error', 'error': r.get('error', '')}
        for r in results if r.get('status') != 'ok'
    ]

    media_fields = [
        'status', 'article_url', 'article_title', 'year', 'gallery_folder',
        'source_url', 'resolved_url', 'path', 'bytes', 'attempts', 'error',
    ]
    gallery_fields = [
        'article_url', 'gallery_ids', 'gallery_folders', 'downloaded_count',
        'failed_count', 'status',
    ]
    failure_fields = ['kind', 'article_url', 'url', 'status', 'error']
    _write_csv(output_dir / 'media_files.csv', results, media_fields)
    _write_csv(output_dir / 'gallery_status.csv', gallery_rows, gallery_fields)
    _write_csv(output_dir / 'failures.csv', failures, failure_fields)

    summary = {
        'articles_scanned': len(articles),
        'unique_media_candidates': len(media_jobs),
        'downloaded': sum(1 for r in results if r.get('status') == 'ok'),
        'media_failed': sum(1 for r in results if r.get('status') != 'ok'),
        'article_pages_failed': len(page_failures),
        'gallery_records': len(gallery_rows),
        'gallery_complete': sum(1 for r in gallery_rows if r.get('status') == 'complete'),
        'gallery_partial': sum(1 for r in gallery_rows if r.get('status') == 'partial'),
        'gallery_missing': sum(1 for r in gallery_rows if r.get('status') in {'missing', 'unresolved'}),
    }
    (output_dir / 'media-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description='Archive Snowmagazin article images and reconstructable galleries.')
    parser.add_argument('--base-url', default=BASE_URL)
    parser.add_argument('--output', default='media_out')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    summary = crawl_media(args.base_url, args.output, args.limit, args.workers)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
