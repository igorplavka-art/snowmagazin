import html as html_lib
import re
import unicodedata
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup

BASE_HOST = 'snowmagazin.relaxmagazin.sk'
SHORTCODE_RE = re.compile(r'\[nggallery\s+id\s*=\s*["\']?(\d+)["\']?[^\]]*\]', re.I)
MEDIA_ATTRS = ('src', 'href', 'data-src', 'data-lazy-src')


def extract_gallery_ids(value):
    seen = set()
    result = []
    for match in SHORTCODE_RE.finditer(value or ''):
        gallery_id = int(match.group(1))
        if gallery_id not in seen:
            seen.add(gallery_id)
            result.append(gallery_id)
    return result


def html_to_text(value):
    value = SHORTCODE_RE.sub('', value or '')
    soup = BeautifulSoup(value, 'html.parser')
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for block in soup.find_all(['p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote']):
        block.insert_after('\n')
    text = soup.get_text(' ')
    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r'\s+', ' ', html_lib.unescape(line)).strip()
        cleaned = re.sub(r'\s+([,.;:!?])', r'\1', cleaned)
        if cleaned:
            lines.append(cleaned)
    return '\n'.join(lines)


def safe_slug(value):
    normalized = unicodedata.normalize('NFKD', value or '')
    ascii_value = normalized.encode('ascii', 'ignore').decode('ascii').lower()
    ascii_value = re.sub(r'[^a-z0-9]+', '-', ascii_value)
    return re.sub(r'-{2,}', '-', ascii_value).strip('-') or 'article'


def extract_media_urls(value):
    soup = BeautifulSoup(value or '', 'html.parser')
    found = []
    seen = set()
    for tag in soup.find_all(True):
        for attr in MEDIA_ATTRS:
            url = tag.get(attr)
            if not url or not isinstance(url, str):
                continue
            if '/wp-content/' not in url and not re.search(r'\.(?:jpe?g|png|gif|webp|mp4)(?:\?|$)', url, re.I):
                continue
            if url not in seen:
                seen.add(url)
                found.append(url)
    return found


def normalize_wp_post(post):
    raw_html = (post.get('content') or {}).get('rendered') or ''
    excerpt_html = (post.get('excerpt') or {}).get('rendered') or ''
    title = html_lib.unescape(BeautifulSoup((post.get('title') or {}).get('rendered') or '', 'html.parser').get_text(' ', strip=True))
    return {
        'id': post.get('id'),
        'published_date': post.get('date'),
        'modified_date': post.get('modified'),
        'url': post.get('link'),
        'slug': post.get('slug') or safe_slug(title),
        'title': title,
        'excerpt_html': excerpt_html,
        'excerpt_text': html_to_text(excerpt_html),
        'html': raw_html,
        'text': html_to_text(raw_html),
        'author_id': post.get('author'),
        'author_name': None,
        'categories': list(post.get('categories') or []),
        'tags': list(post.get('tags') or []),
        'nggallery_ids': extract_gallery_ids(raw_html),
        'media_urls': extract_media_urls(raw_html),
        'source_method': 'wp_rest',
    }


def is_article_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {'http', 'https'} or parsed.netloc.lower() != BASE_HOST:
        return False
    query = parse_qs(parsed.query)
    if query.get('p') and any(v.isdigit() for v in query['p']):
        return True
    path = re.sub(r'/+', '/', parsed.path or '/').strip('/')
    if not path:
        return False
    lowered = path.lower()
    blocked_prefixes = (
        'wp-admin', 'wp-json', 'wp-content', 'wp-includes',
        'kategoria/', 'category/', 'znacka/', 'tag/', 'author/',
        'page/', 'feed', 'search/', 'attachment/', 'comments/',
    )
    if lowered == 'feed' or any(lowered.startswith(prefix) for prefix in blocked_prefixes):
        return False
    if re.search(r'\.(?:jpg|jpeg|png|gif|webp|svg|css|js|xml|txt|pdf|zip)$', lowered):
        return False
    return '/' not in path
