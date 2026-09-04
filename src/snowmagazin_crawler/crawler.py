import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .archive import error_row, write_article, write_manifest
from .core import extract_gallery_ids, extract_media_urls, html_to_text, safe_slug, normalize_wp_post
from .discovery import discover_article_urls, iter_wp_posts

DEFAULT_BASE_URL = 'https://snowmagazin.relaxmagazin.sk'
USER_AGENT = 'SnowmagazinArchiveCrawler/1.0 (+historical archive; contact via repository owner)'


def _normalize_url(url):
    if not url:
        return ''
    parsed = urlparse(url)
    path = parsed.path or '/'
    if path != '/':
        path = path.rstrip('/') + '/'
    query = f'?{parsed.query}' if parsed.query else ''
    return f'{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}'


def _meta_content(soup, *, property_name=None, name=None):
    attrs = {}
    if property_name:
        attrs['property'] = property_name
    if name:
        attrs['name'] = name
    tag = soup.find('meta', attrs=attrs)
    return tag.get('content', '').strip() if tag and tag.get('content') else ''


def _jsonld_date(soup):
    for script in soup.find_all('script', type='application/ld+json'):
        raw = script.string or script.get_text() or ''
        try:
            data = json.loads(raw)
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict):
                if item.get('datePublished'):
                    return str(item['datePublished'])
                graph = item.get('@graph')
                if isinstance(graph, list):
                    for node in graph:
                        if isinstance(node, dict) and node.get('datePublished'):
                            return str(node['datePublished'])
    return ''


def extract_article_from_html(url, page_html):
    soup = BeautifulSoup(page_html or '', 'html.parser')
    canonical_tag = soup.find('link', rel=lambda value: value and 'canonical' in value)
    canonical = canonical_tag.get('href', '').strip() if canonical_tag else ''
    canonical = canonical or url

    title_tag = (
        soup.select_one('h1.entry-title')
        or soup.select_one('h1.post-title')
        or soup.select_one('article h1')
        or soup.find('h1')
    )
    title = title_tag.get_text(' ', strip=True) if title_tag else _meta_content(soup, property_name='og:title')
    if not title:
        raise ValueError('article title not found')

    content = None
    for selector in (
        '.entry-content', '.post-content', '.td-post-content', '.article-content',
        '.single-post-content', '.post-entry', 'article .content',
    ):
        content = soup.select_one(selector)
        if content:
            break
    if content is None:
        content = soup.find('article')
    if content is None:
        raise ValueError('article body not found')

    body_html = content.decode_contents()
    body_text = html_to_text(body_html)
    if not body_text:
        raise ValueError('article body is empty')

    published = _meta_content(soup, property_name='article:published_time')
    if not published:
        time_tag = soup.find('time', datetime=True)
        published = time_tag.get('datetime', '').strip() if time_tag else ''
    if not published:
        published = _jsonld_date(soup)
    modified = _meta_content(soup, property_name='article:modified_time')

    author = _meta_content(soup, name='author')
    if not author:
        author_tag = soup.select_one('[rel="author"], .author-name, .post-author-name')
        author = author_tag.get_text(' ', strip=True) if author_tag else ''

    category_names = []
    tag_names = []
    for anchor in soup.find_all('a', href=True):
        href = anchor.get('href', '')
        text = anchor.get_text(' ', strip=True)
        if not text:
            continue
        if '/kategoria/' in href or '/category/' in href:
            if text not in category_names:
                category_names.append(text)
        elif '/znacka/' in href or '/tag/' in href:
            if text not in tag_names:
                tag_names.append(text)

    path_slug = urlparse(canonical).path.strip('/').split('/')[-1]
    slug = safe_slug(path_slug or title)
    return {
        'id': None,
        'published_date': published,
        'modified_date': modified,
        'url': canonical,
        'slug': slug,
        'title': title,
        'excerpt_html': '',
        'excerpt_text': '',
        'html': body_html,
        'text': body_text,
        'author_id': None,
        'author_name': author,
        'categories': category_names,
        'tags': tag_names,
        'nggallery_ids': extract_gallery_ids(body_html),
        'media_urls': extract_media_urls(body_html),
        'source_method': 'html_fallback',
    }


def _minimal_fallback_article(url):
    path_slug = urlparse(url).path.strip('/').split('/')[-1]
    return {
        'id': None,
        'published_date': '',
        'modified_date': '',
        'url': url,
        'slug': safe_slug(path_slug or 'article'),
        'title': path_slug.replace('-', ' ') if path_slug else url,
        'author_id': None,
        'author_name': '',
        'categories': [],
        'tags': [],
        'nggallery_ids': [],
        'media_urls': [],
        'source_method': 'html_fallback',
    }


def crawl(*, session=None, base_url=DEFAULT_BASE_URL, output_dir='out', limit=None, delay=0.15):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if session is None:
        session = requests.Session()
    if hasattr(session, 'headers'):
        session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8'})

    rows = []
    seen_ids = set()
    seen_urls = set()
    ok_count = 0

    for post in iter_wp_posts(session, base_url, limit=limit):
        try:
            article = normalize_wp_post(post)
            post_id = article.get('id')
            url_key = _normalize_url(article.get('url'))
            if post_id in seen_ids or (url_key and url_key in seen_urls):
                continue
            rows.append(write_article(article, output_dir))
            ok_count += 1
            if post_id is not None:
                seen_ids.add(post_id)
            if url_key:
                seen_urls.add(url_key)
        except Exception as exc:
            article = _minimal_fallback_article(post.get('link') or '')
            article['id'] = post.get('id')
            rows.append(error_row(article, exc))
        if limit is not None and ok_count >= limit:
            break

    if limit is None or ok_count < limit:
        for url in discover_article_urls(session, base_url):
            url_key = _normalize_url(url)
            if url_key in seen_urls:
                continue
            if limit is not None and ok_count >= limit:
                break
            minimal = _minimal_fallback_article(url)
            try:
                response = session.get(url, timeout=30)
                status = getattr(response, 'status_code', 200)
                if status >= 400:
                    raise RuntimeError(f'HTTP {status}')
                article = extract_article_from_html(url, getattr(response, 'text', '') or '')
                canonical_key = _normalize_url(article.get('url'))
                if canonical_key and canonical_key in seen_urls:
                    seen_urls.add(url_key)
                    continue
                rows.append(write_article(article, output_dir))
                ok_count += 1
                seen_urls.add(url_key)
                if canonical_key:
                    seen_urls.add(canonical_key)
            except Exception as exc:
                rows.append(error_row(minimal, exc))
                seen_urls.add(url_key)
            if delay:
                time.sleep(delay)

    write_manifest(rows, output_dir / 'articles.csv')
    error_count = sum(1 for row in rows if row.get('status') == 'error')
    return {'ok': ok_count, 'errors': error_count, 'total_rows': len(rows)}
