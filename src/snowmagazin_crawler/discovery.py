from collections import deque
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .core import is_article_url

SITEMAP_CANDIDATES = ('/wp-sitemap.xml', '/post-sitemap.xml', '/sitemap_index.xml')
KNOWN_CATEGORY_SLUGS = (
    'trening', 'freeride', 'people', 'poradna-snow', 'strediska',
    'race', 'equip', 'exotika', 'kviz-zimny',
)


def iter_wp_posts(session, base_url, limit=None):
    endpoint = base_url.rstrip('/') + '/wp-json/wp/v2/posts'
    yielded = 0
    page = 1
    total_pages = None
    while True:
        response = session.get(endpoint, params={'per_page': 100, 'page': page}, timeout=30)
        if getattr(response, 'status_code', 200) >= 400:
            break
        try:
            items = response.json()
        except Exception:
            break
        if not isinstance(items, list) or not items:
            break
        if total_pages is None:
            try:
                total_pages = int((getattr(response, 'headers', {}) or {}).get('X-WP-TotalPages') or 0) or None
            except (TypeError, ValueError):
                total_pages = None
        for item in items:
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        if total_pages is not None and page >= total_pages:
            break
        if len(items) < 100 and total_pages is None:
            break
        page += 1


def _safe_get_text(session, url):
    try:
        response = session.get(url, timeout=30)
    except Exception:
        return None
    if getattr(response, 'status_code', 200) >= 400:
        return None
    return getattr(response, 'text', '') or ''


def _loc_values(text):
    try:
        root = ET.fromstring(text or '')
    except ET.ParseError:
        return []
    values = []
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1].lower() == 'loc' and element.text:
            value = element.text.strip()
            if value:
                values.append(value)
    return values


def _is_archive_navigation(url, host):
    parsed = urlparse(url)
    if parsed.netloc.lower() != host:
        return False
    path = parsed.path.lower()
    return (
        path == '/'
        or path.startswith('/kategoria/')
        or path.startswith('/category/')
        or '/page/' in path and (path.startswith('/kategoria/') or path.startswith('/category/'))
    )


def discover_article_urls(session, base_url, max_pages=None):
    base_url = base_url.rstrip('/')
    host = urlparse(base_url).netloc.lower()
    articles = set()

    sitemap_queue = deque(urljoin(base_url + '/', path.lstrip('/')) for path in SITEMAP_CANDIDATES)
    seen_sitemaps = set()
    while sitemap_queue:
        sitemap_url = sitemap_queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        text = _safe_get_text(session, sitemap_url)
        if not text:
            continue
        for loc in _loc_values(text):
            parsed = urlparse(loc)
            if parsed.netloc.lower() != host:
                continue
            if loc.lower().endswith('.xml'):
                if loc not in seen_sitemaps:
                    sitemap_queue.append(loc)
            elif is_article_url(loc):
                articles.add(loc)

    archive_queue = deque([base_url + '/'])
    archive_queue.extend(f'{base_url}/kategoria/{slug}/' for slug in KNOWN_CATEGORY_SLUGS)
    seen_pages = set()
    fetched_pages = 0
    while archive_queue:
        if max_pages is not None and fetched_pages >= max_pages:
            break
        page_url = archive_queue.popleft()
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        text = _safe_get_text(session, page_url)
        fetched_pages += 1
        if not text:
            continue
        soup = BeautifulSoup(text, 'html.parser')
        for anchor in soup.find_all('a', href=True):
            url = urljoin(page_url, anchor['href']).split('#', 1)[0]
            if is_article_url(url):
                articles.add(url)
            elif _is_archive_navigation(url, host) and url not in seen_pages:
                archive_queue.appendleft(url)

    return sorted(articles)
