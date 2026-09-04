import csv
import json
import re
from pathlib import Path

from .core import safe_slug

MANIFEST_FIELDS = [
    'id', 'title', 'url', 'published_date', 'modified_date', 'year', 'slug',
    'author_id', 'author_name', 'categories', 'tags', 'nggallery_ids',
    'media_urls', 'source_method', 'archive_path', 'status', 'error',
]


def article_key(article):
    if article.get('id') is not None:
        return f"id:{article['id']}"
    if article.get('url'):
        return f"url:{article['url']}"
    return f"slug:{article.get('slug') or safe_slug(article.get('title') or 'article')}"


def _date_and_year(article):
    value = article.get('published_date') or ''
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})', value)
    if match:
        return match.group(0), match.group(1)
    year_match = re.match(r'^(\d{4})', value)
    if year_match:
        return year_match.group(1) + '-00-00', year_match.group(1)
    return 'unknown-date', 'unknown'


def _manifest_row(article, archive_path='', status='ok', error=''):
    _, year = _date_and_year(article)
    return {
        'id': article.get('id'),
        'title': article.get('title') or '',
        'url': article.get('url') or '',
        'published_date': article.get('published_date') or '',
        'modified_date': article.get('modified_date') or '',
        'year': year,
        'slug': article.get('slug') or safe_slug(article.get('title') or 'article'),
        'author_id': article.get('author_id'),
        'author_name': article.get('author_name') or '',
        'categories': article.get('categories') or [],
        'tags': article.get('tags') or [],
        'nggallery_ids': article.get('nggallery_ids') or [],
        'media_urls': article.get('media_urls') or [],
        'source_method': article.get('source_method') or '',
        'archive_path': archive_path,
        'status': status,
        'error': error,
    }


def error_row(article, error):
    return _manifest_row(article, status='error', error=str(error))


def write_article(article, output_dir):
    output_dir = Path(output_dir)
    date_part, year = _date_and_year(article)
    slug = safe_slug(article.get('slug') or article.get('title') or 'article')
    rel_path = Path('archive') / year / f'{date_part}-{slug}'
    folder = output_dir / rel_path
    folder.mkdir(parents=True, exist_ok=True)

    metadata = {k: v for k, v in article.items() if k not in {'html', 'text'}}
    metadata['archive_path'] = rel_path.as_posix()
    (folder / 'metadata.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8',
    )
    (folder / 'published.html').write_text(article.get('html') or '', encoding='utf-8')
    (folder / 'published.txt').write_text(article.get('text') or '', encoding='utf-8')
    return _manifest_row(article, rel_path.as_posix(), status='ok')


def _csv_value(value):
    if isinstance(value, (list, tuple, set)):
        return ';'.join(str(item) for item in value)
    if value is None:
        return ''
    return str(value)


def write_manifest(rows, csv_path):
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field, '')) for field in MANIFEST_FIELDS})
