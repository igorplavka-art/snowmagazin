import argparse
import csv
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .core import extract_gallery_ids

CDX_ENDPOINT = 'https://web.archive.org/cdx/search/cdx'
WAYBACK_BASE = 'https://web.archive.org/web'
GALLERY_FOLDER_RE = re.compile(r'/wp-content/gallery/([^/\s"\'<>?#]+)/', re.I)
GALLERY_IMAGE_RE = re.compile(
    r'/wp-content/gallery/([^/\s"\'<>?#]+)/(.+?\.(?:jpe?g|png|gif|webp))(?:[?#]|$)',
    re.I,
)
NGG_CONTAINER_RE = re.compile(r'ngg-gallery-(\d+)(?:-|\b)', re.I)
IMAGE_MIME_RE = re.compile(r'^image/', re.I)


def build_cdx_url(url, match_type='exact', *, image_only=False, limit=200):
    params = [
        ('url', url),
        ('output', 'json'),
        ('fl', 'timestamp,original,mimetype,statuscode,digest'),
        ('filter', 'statuscode:200'),
        ('collapse', 'urlkey' if match_type == 'prefix' else 'digest'),
        ('limit', str(limit)),
    ]
    if match_type != 'exact':
        params.append(('matchType', match_type))
    if image_only:
        params.append(('filter', 'mimetype:image/.*'))
    return CDX_ENDPOINT + '?' + urlencode(params)


def _rows_from_payload(payload):
    text = (payload or '').strip()
    if not text:
        return []
    if text.startswith('['):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not data:
            return []
        if isinstance(data[0], list):
            return data
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(line.split())
    return rows


def parse_cdx_rows(payload):
    raw_rows = _rows_from_payload(payload)
    if not raw_rows:
        return []
    header = [str(x).lower() for x in raw_rows[0]]
    if 'timestamp' in header and 'original' in header:
        data_rows = raw_rows[1:]
    else:
        header = ['timestamp', 'original', 'mimetype', 'statuscode', 'digest']
        data_rows = raw_rows
    idx = {name: pos for pos, name in enumerate(header)}
    result = []
    seen = set()
    for row in data_rows:
        try:
            original = row[idx['original']]
            timestamp = row[idx['timestamp']]
        except (IndexError, KeyError):
            continue
        if original in seen:
            continue
        seen.add(original)
        def get(name, default=''):
            try:
                return row[idx[name]]
            except (IndexError, KeyError):
                return default
        result.append({
            'timestamp': timestamp,
            'original': original,
            'mimetype': get('mimetype'),
            'statuscode': get('statuscode'),
        })
    return result


def select_image_snapshot(rows):
    if not rows:
        return None
    header = [str(x).lower() for x in rows[0]] if isinstance(rows[0], list) else []
    if 'timestamp' in header:
        idx = {name: pos for pos, name in enumerate(header)}
        data = rows[1:]
        candidates = []
        for row in data:
            try:
                item = {
                    'timestamp': row[idx['timestamp']],
                    'original': row[idx['original']],
                    'mimetype': row[idx.get('mimetype', -1)] if 'mimetype' in idx else '',
                    'statuscode': row[idx.get('statuscode', -1)] if 'statuscode' in idx else '',
                }
            except (IndexError, KeyError):
                continue
            candidates.append(item)
    else:
        candidates = rows
    valid = [
        item for item in candidates
        if str(item.get('statuscode', '200')) == '200'
        and IMAGE_MIME_RE.search(str(item.get('mimetype', 'image/unknown')))
    ]
    if not valid:
        return None
    return max(valid, key=lambda item: str(item.get('timestamp', '')))


def wayback_raw_url(snapshot):
    return f"{WAYBACK_BASE}/{snapshot['timestamp']}id_/{snapshot['original']}"


def extract_wayback_snapshot_folders(html):
    folders = []
    for match in GALLERY_FOLDER_RE.finditer(html or ''):
        folder = match.group(1)
        if folder not in folders:
            folders.append(folder)
    return folders


def extract_wayback_gallery_pairs(html):
    soup = BeautifulSoup(html or '', 'html.parser')
    pairs = defaultdict(list)
    for tag in soup.find_all(id=True):
        match = NGG_CONTAINER_RE.search(str(tag.get('id', '')))
        if not match:
            continue
        gid = int(match.group(1))
        for folder in extract_wayback_snapshot_folders(str(tag)):
            if folder not in pairs[gid]:
                pairs[gid].append(folder)
    return dict(pairs)


def _safe_get(session, url, *, timeout=45, attempts=4):
    last_error = ''
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 429:
                last_error = 'HTTP 429'
                delay = min(20.0, 2.0 * (attempt + 1))
                time.sleep(delay)
                continue
            if response.status_code >= 500:
                last_error = f'HTTP {response.status_code}'
                time.sleep(min(12.0, 1.5 * (attempt + 1)))
                continue
            return response, ''
        except Exception as exc:
            last_error = f'{type(exc).__name__}: {exc}'
            time.sleep(min(10.0, 1.5 * (attempt + 1)))
    return None, last_error


def query_cdx(session, url, match_type='exact', *, image_only=False, limit=200):
    query_url = build_cdx_url(url, match_type, image_only=image_only, limit=limit)
    response, error = _safe_get(session, query_url, timeout=60)
    if response is None:
        return [], {'query_url': query_url, 'status_code': '', 'error': error}
    if response.status_code >= 400:
        return [], {
            'query_url': query_url,
            'status_code': response.status_code,
            'error': f'HTTP {response.status_code}',
        }
    rows = parse_cdx_rows(response.text)
    return rows, {'query_url': query_url, 'status_code': response.status_code, 'error': ''}


def _article_records(archive_root):
    records = []
    for metadata_path in sorted(Path(archive_root).rglob('metadata.json')):
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except Exception:
            continue
        ids = metadata.get('nggallery_ids') or []
        if isinstance(ids, str):
            ids = [part for part in re.split(r'[;,\s]+', ids) if part]
        parsed_ids = []
        for value in ids:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value not in parsed_ids:
                parsed_ids.append(value)
        if not parsed_ids:
            html_path = metadata_path.parent / 'published.html'
            html = html_path.read_text(encoding='utf-8', errors='replace') if html_path.exists() else ''
            parsed_ids = [int(x) for x in extract_gallery_ids(html)]
        if not parsed_ids:
            continue
        published = str(metadata.get('published_date') or metadata.get('date') or '')
        records.append({
            'ids': parsed_ids,
            'url': str(metadata.get('url') or ''),
            'published_date': published,
            'title': str(metadata.get('title') or ''),
        })
    return records


def article_url_variants(url, published_date=''):
    parsed = urlparse(url)
    slug = parsed.path.strip('/').split('/')[-1] if parsed.path.strip('/') else ''
    variants = []
    def add(value):
        if value and value not in variants:
            variants.append(value)
    add(url)
    for scheme in ('http', 'https'):
        for host in ('www.snowmagazin.sk', 'snowmagazin.sk'):
            add(urlunparse((scheme, host, parsed.path or '/', '', '', '')))
    match = re.match(r'(\d{4})-(\d{2})', published_date)
    if match and slug:
        year, month = match.groups()
        dated_path = f'/{year}/{month}/{slug}/'
        for scheme in ('http', 'https'):
            for host in ('www.snowmagazin.sk', 'snowmagazin.sk'):
                add(urlunparse((scheme, host, dated_path, '', '', '')))
    return variants


def _fetch_html_snapshot(session, row):
    url = wayback_raw_url(row)
    response, error = _safe_get(session, url, timeout=60)
    if response is None:
        return '', error
    if response.status_code >= 400:
        return '', f'HTTP {response.status_code}'
    content_type = response.headers.get('Content-Type', '')
    if 'html' not in content_type.lower() and '<html' not in response.text[:1000].lower():
        return '', f'not-html {content_type}'
    return response.text, ''


def map_gallery_ids_from_wayback(session, archive_root):
    records = _article_records(archive_root)
    known_ids = sorted({gid for record in records for gid in record['ids']})
    mapped = defaultdict(set)
    evidence_rows = []
    query_rows = []
    for record in records:
        unresolved = [gid for gid in record['ids'] if not mapped.get(gid)]
        if not unresolved:
            continue
        resolved_record = False
        for candidate in article_url_variants(record['url'], record['published_date']):
            captures, query_meta = query_cdx(session, candidate, 'exact', image_only=False, limit=20)
            query_rows.append({
                'kind': 'article', 'gallery_ids': ';'.join(map(str, record['ids'])),
                'target': candidate, 'captures': len(captures), **query_meta,
            })
            if not captures:
                continue
            for capture in reversed(captures):
                html, error = _fetch_html_snapshot(session, capture)
                if not html:
                    evidence_rows.append({
                        'gallery_ids': ';'.join(map(str, record['ids'])),
                        'article_url': record['url'], 'candidate_url': candidate,
                        'timestamp': capture.get('timestamp', ''), 'folders': '',
                        'method': 'snapshot_fetch_error', 'error': error,
                    })
                    continue
                direct_pairs = extract_wayback_gallery_pairs(html)
                if direct_pairs:
                    for gid, folders in direct_pairs.items():
                        if gid not in record['ids']:
                            continue
                        for folder in folders:
                            mapped[gid].add(folder)
                    evidence_rows.append({
                        'gallery_ids': ';'.join(map(str, record['ids'])),
                        'article_url': record['url'], 'candidate_url': candidate,
                        'timestamp': capture.get('timestamp', ''),
                        'folders': ';'.join(extract_wayback_snapshot_folders(html)),
                        'method': 'rendered_ngg_container', 'error': '',
                    })
                else:
                    folders = extract_wayback_snapshot_folders(html)
                    target_ids = [gid for gid in record['ids'] if not mapped.get(gid)]
                    if len(target_ids) == 1 and folders:
                        for folder in folders:
                            mapped[target_ids[0]].add(folder)
                        evidence_rows.append({
                            'gallery_ids': str(target_ids[0]),
                            'article_url': record['url'], 'candidate_url': candidate,
                            'timestamp': capture.get('timestamp', ''),
                            'folders': ';'.join(folders),
                            'method': 'single_id_article_snapshot', 'error': '',
                        })
                if all(mapped.get(gid) for gid in record['ids']):
                    resolved_record = True
                    break
            if resolved_record:
                break
            time.sleep(0.08)
    return known_ids, mapped, evidence_rows, query_rows


def enumerate_global_gallery_index(session):
    all_rows = []
    query_rows = []
    seen = set()
    prefixes = (
        'http://www.snowmagazin.sk/wp-content/gallery/',
        'https://www.snowmagazin.sk/wp-content/gallery/',
        'http://snowmagazin.sk/wp-content/gallery/',
        'https://snowmagazin.sk/wp-content/gallery/',
    )
    for prefix in prefixes:
        rows, meta = query_cdx(session, prefix, 'prefix', image_only=True, limit=50000)
        query_rows.append({'kind': 'gallery_prefix', 'target': prefix, 'captures': len(rows), **meta})
        for row in rows:
            key = row['original']
            if key in seen:
                continue
            seen.add(key)
            match = GALLERY_IMAGE_RE.search(urlparse(key).path)
            if not match:
                continue
            folder = match.group(1)
            relative = match.group(2)
            kind = 'thumbnail' if '/thumbs/' in urlparse(key).path.lower() else (
                'backup' if '/backup/' in urlparse(key).path.lower() else 'original'
            )
            all_rows.append({**row, 'folder': folder, 'relative_path': relative, 'asset_kind': kind})
        time.sleep(0.2)
    return all_rows, query_rows


def _write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, '') for field in fields})


def recover_wayback_index(archive_root, output_dir='wayback_out'):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'SnowmagazinArchiveRecovery/1.0 (+historical preservation)',
        'Accept': 'application/json,text/plain,text/html;q=0.9,*/*;q=0.8',
    })

    known_ids, mapped, evidence_rows, article_queries = map_gallery_ids_from_wayback(session, archive_root)
    gallery_rows, prefix_queries = enumerate_global_gallery_index(session)
    folders_in_index = defaultdict(int)
    for row in gallery_rows:
        folders_in_index[row['folder']] += 1

    mapping_rows = []
    for gid in known_ids:
        folders = sorted(mapped.get(gid, set()))
        mapping_rows.append({
            'gallery_id': gid,
            'folders': ';'.join(folders),
            'files_visible_in_global_index': sum(folders_in_index.get(folder, 0) for folder in folders),
            'status': 'mapped' if folders else 'unresolved',
        })

    _write_csv(output_dir / 'wayback_gallery_id_mapping.csv', mapping_rows,
               ['gallery_id','folders','files_visible_in_global_index','status'])
    _write_csv(output_dir / 'wayback_article_evidence.csv', evidence_rows,
               ['gallery_ids','article_url','candidate_url','timestamp','folders','method','error'])
    _write_csv(output_dir / 'wayback_gallery_files_index.csv', gallery_rows,
               ['folder','asset_kind','relative_path','timestamp','original','mimetype','statuscode'])
    _write_csv(output_dir / 'wayback_queries.csv', article_queries + prefix_queries,
               ['kind','gallery_ids','target','captures','query_url','status_code','error'])
    unresolved = [row for row in mapping_rows if row['status'] == 'unresolved']
    _write_csv(output_dir / 'wayback_unresolved_gallery_ids.csv', unresolved,
               ['gallery_id','folders','files_visible_in_global_index','status'])

    summary = {
        'gallery_ids_total': len(known_ids),
        'gallery_ids_mapped_wayback': len(mapping_rows) - len(unresolved),
        'gallery_ids_unresolved_wayback': len(unresolved),
        'global_gallery_files_indexed': len(gallery_rows),
        'global_gallery_folders_indexed': len(folders_in_index),
        'global_originals_indexed': sum(1 for row in gallery_rows if row['asset_kind'] == 'original'),
        'global_thumbnails_indexed': sum(1 for row in gallery_rows if row['asset_kind'] == 'thumbnail'),
        'global_backups_indexed': sum(1 for row in gallery_rows if row['asset_kind'] == 'backup'),
    }
    (output_dir / 'wayback-summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description='Index legacy Snowmagazin NextGEN galleries using the Internet Archive CDX service.')
    parser.add_argument('--archive-root', required=True)
    parser.add_argument('--output', default='wayback_out')
    args = parser.parse_args()
    print(json.dumps(recover_wayback_index(args.archive_root, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
