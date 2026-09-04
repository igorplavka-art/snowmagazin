import argparse
import csv
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .core import extract_gallery_ids, safe_slug
from .media import _looks_like_image, media_candidates

BASE_URL = 'https://snowmagazin.relaxmagazin.sk'
LEGACY_BASES = (
    'https://snowmagazin.relaxmagazin.sk',
    'https://www.snowmagazin.sk',
    'http://www.snowmagazin.sk',
)
IMAGE_RE = re.compile(r'\.(?:jpe?g|png|gif|webp)(?:\?.*)?$', re.I)
GALLERY_PATH_RE = re.compile(r'/wp-content/gallery/([^/]+)/([^\s"\'<>?#]+\.(?:jpe?g|png|gif|webp))(?:\?[^\s"\'<>]*)?', re.I)
MRSS_PATHS = (
    '/wp-content/plugins/nextgen-gallery/xml/media-rss.php?gid={gid}&mode=gallery',
    '/wp-content/plugins/nextgen-gallery/src/Legacy/xml/media-rss.php?gid={gid}&mode=gallery',
)


def _clean_url(url):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', parsed.query, ''))


def _add_unique(seq, value):
    if value not in seq:
        seq.append(value)


def extract_gallery_evidence(page_html, page_url, metadata_ids=None):
    html = page_html or ''
    gallery_ids = []
    for value in metadata_ids or []:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        _add_unique(gallery_ids, value)
    for value in extract_gallery_ids(html):
        _add_unique(gallery_ids, int(value))

    explicit_urls = []
    folders = []
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(True):
        for attr in ('src', 'href', 'data-src', 'data-full-url', 'data-image'):
            raw = tag.get(attr)
            if not raw or '/wp-content/gallery/' not in str(raw):
                continue
            url = _clean_url(urljoin(page_url, str(raw)))
            match = GALLERY_PATH_RE.search(url)
            if not match:
                continue
            _add_unique(explicit_urls, url)
            _add_unique(folders, match.group(1))

    for match in GALLERY_PATH_RE.finditer(html):
        raw_path = match.group(0)
        if raw_path.startswith('http'):
            url = _clean_url(raw_path)
        else:
            url = _clean_url(urljoin(page_url, raw_path))
        _add_unique(explicit_urls, url)
        _add_unique(folders, match.group(1))

    pairs = []
    if gallery_ids and folders:
        if len(gallery_ids) == 1:
            pairs = [(gallery_ids[0], folder) for folder in folders]
        elif len(folders) == 1:
            pairs = [(gallery_id, folders[0]) for gallery_id in gallery_ids]
        elif len(gallery_ids) == len(folders):
            pairs = list(zip(gallery_ids, folders))

    return {
        'gallery_ids': gallery_ids,
        'folders': folders,
        'explicit_urls': explicit_urls,
        'id_folder_pairs': pairs,
    }


def extract_index_images(index_html, index_url):
    soup = BeautifulSoup(index_html or '', 'html.parser')
    base = urlparse(index_url)
    base_path = base.path if base.path.endswith('/') else base.path + '/'
    found = []
    for anchor in soup.find_all('a', href=True):
        href = anchor.get('href', '').strip()
        if not href or href.startswith(('../', './', '#', '?')) or href.endswith('/'):
            continue
        url = _clean_url(urljoin(index_url, href))
        parsed = urlparse(url)
        if parsed.netloc.lower() != base.netloc.lower():
            continue
        if not parsed.path.startswith(base_path):
            continue
        remainder = parsed.path[len(base_path):]
        if '/' in remainder or not IMAGE_RE.search(parsed.path):
            continue
        _add_unique(found, url)
    return found


def extract_mrss_images(xml_text, base_url=BASE_URL):
    text = xml_text or ''
    found = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None
    if root is not None:
        for element in root.iter():
            local = element.tag.rsplit('}', 1)[-1].lower()
            if local not in {'content', 'enclosure'}:
                continue
            raw = element.attrib.get('url') or element.attrib.get('href') or ''
            if not raw:
                continue
            url = _clean_url(urljoin(base_url, raw))
            if IMAGE_RE.search(urlparse(url).path) and '/wp-content/gallery/' in urlparse(url).path.lower():
                _add_unique(found, url)
    if not found:
        for match in GALLERY_PATH_RE.finditer(text):
            raw = match.group(0)
            url = _clean_url(raw if raw.startswith('http') else urljoin(base_url, raw))
            if '/thumbs/' not in urlparse(url).path.lower():
                _add_unique(found, url)
    return found


def gallery_status(*, gallery_ids, folders, explicit_count, indexed_count,
                   downloaded_count, failed_count, indexable):
    if indexable:
        if downloaded_count and failed_count == 0 and downloaded_count >= indexed_count:
            return 'complete'
        if downloaded_count:
            return 'partial'
        return 'missing'
    if downloaded_count or explicit_count:
        return 'partial'
    if gallery_ids and not folders:
        return 'unresolved'
    if folders:
        return 'missing'
    return 'unresolved'


def _metadata_ids(metadata):
    ids = metadata.get('nggallery_ids') or []
    if isinstance(ids, str):
        ids = [part for part in re.split(r'[;,\s]+', ids) if part]
    result = []
    for value in ids:
        try:
            _add_unique(result, int(value))
        except (TypeError, ValueError):
            pass
    return result


def scan_archive(archive_root):
    archive_root = Path(archive_root)
    articles = []
    all_ids = set()
    id_to_folders = defaultdict(set)
    folder_to_urls = defaultdict(set)
    folder_to_articles = defaultdict(set)
    id_to_articles = defaultdict(set)

    for metadata_path in sorted(archive_root.rglob('metadata.json')):
        article_dir = metadata_path.parent
        html_path = article_dir / 'published.html'
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except Exception:
            continue
        html = html_path.read_text(encoding='utf-8', errors='replace') if html_path.exists() else ''
        page_url = metadata.get('url') or ''
        evidence = extract_gallery_evidence(html, page_url, _metadata_ids(metadata))
        if not evidence['gallery_ids'] and not evidence['folders'] and not evidence['explicit_urls']:
            continue
        for gid in evidence['gallery_ids']:
            all_ids.add(gid)
            id_to_articles[gid].add(page_url)
        for gid, folder in evidence['id_folder_pairs']:
            id_to_folders[gid].add(folder)
        for folder in evidence['folders']:
            folder_to_articles[folder].add(page_url)
        for url in evidence['explicit_urls']:
            match = GALLERY_PATH_RE.search(urlparse(url).path)
            if match:
                folder_to_urls[match.group(1)].add(url)
        articles.append({
            'article_url': page_url,
            'title': metadata.get('title') or '',
            'gallery_ids': evidence['gallery_ids'],
            'folders': evidence['folders'],
            'explicit_urls': evidence['explicit_urls'],
        })
    return {
        'articles': articles,
        'all_ids': all_ids,
        'id_to_folders': id_to_folders,
        'folder_to_urls': folder_to_urls,
        'folder_to_articles': folder_to_articles,
        'id_to_articles': id_to_articles,
    }


def _probe_folder(session, folder):
    probes = []
    images = []
    indexable = False
    for base in LEGACY_BASES:
        url = f'{base.rstrip("/")}/wp-content/gallery/{folder}/'
        try:
            response = session.get(url, timeout=35, allow_redirects=True)
            status = response.status_code
            body = response.text if status < 400 else ''
            found = extract_index_images(body, response.url or url) if body else []
            looks_indexed = bool(found) and (
                'index of' in body.lower() or '/wp-content/gallery/' in body.lower()
            )
            if looks_indexed:
                indexable = True
                for image in found:
                    _add_unique(images, image)
            probes.append({
                'folder': folder, 'probe_url': url, 'status_code': status,
                'final_url': response.url or '', 'indexable': looks_indexed,
                'images_found': len(found), 'error': '',
            })
            if looks_indexed:
                break
        except Exception as exc:
            probes.append({
                'folder': folder, 'probe_url': url, 'status_code': '',
                'final_url': '', 'indexable': False, 'images_found': 0,
                'error': f'{type(exc).__name__}: {exc}',
            })
        time.sleep(0.15)
    return probes, images, indexable


def _probe_mrss(session, gallery_id):
    probes = []
    images = []
    for base in LEGACY_BASES:
        for path in MRSS_PATHS:
            url = base.rstrip('/') + path.format(gid=gallery_id)
            try:
                response = session.get(url, timeout=35, allow_redirects=True)
                body = response.text if response.status_code < 400 else ''
                found = extract_mrss_images(body, response.url or url) if body else []
                probes.append({
                    'gallery_id': gallery_id, 'probe_url': url,
                    'status_code': response.status_code, 'final_url': response.url or '',
                    'images_found': len(found), 'error': '',
                })
                if found:
                    images = found
                    return probes, images
            except Exception as exc:
                probes.append({
                    'gallery_id': gallery_id, 'probe_url': url,
                    'status_code': '', 'final_url': '', 'images_found': 0,
                    'error': f'{type(exc).__name__}: {exc}',
                })
            time.sleep(0.08)
    return probes, images


def _filename(url):
    return Path(urlparse(url).path).name or 'image.jpg'


def _download_one(session, source_url, destination):
    last_error = ''
    for candidate in media_candidates(source_url, BASE_URL):
        for attempt in range(4):
            try:
                response = session.get(candidate, timeout=45, allow_redirects=True)
                if response.status_code == 429:
                    last_error = 'HTTP 429'
                    retry_after = response.headers.get('Retry-After')
                    try:
                        delay = float(retry_after)
                    except Exception:
                        delay = 1.5 * (attempt + 1)
                    time.sleep(max(1.0, min(delay, 12.0)))
                    continue
                if response.status_code >= 500:
                    last_error = f'HTTP {response.status_code}'
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    last_error = f'HTTP {response.status_code}'
                    break
                if not _looks_like_image(response.content, response.headers.get('Content-Type', '')):
                    last_error = f'not-image content-type={response.headers.get("Content-Type", "unknown")}'
                    break
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.content)
                return {
                    'status': 'ok', 'source_url': source_url,
                    'resolved_url': candidate, 'path': str(destination),
                    'bytes': len(response.content), 'error': '',
                }
            except Exception as exc:
                last_error = f'{type(exc).__name__}: {exc}'
                time.sleep(1.0 * (attempt + 1))
    return {
        'status': 'error', 'source_url': source_url,
        'resolved_url': '', 'path': str(destination), 'bytes': 0,
        'error': last_error,
    }


def _write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fields})


def recover_galleries(archive_root, output_dir='gallery_out'):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scan = scan_archive(archive_root)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (compatible; SnowmagazinGalleryArchive/1.0)',
        'Accept': 'application/rss+xml,application/xml,text/xml,text/html,image/avif,image/webp,image/*,*/*;q=0.8',
        'Referer': BASE_URL + '/',
    })

    mrss_probe_rows = []
    id_to_mrss_urls = defaultdict(set)
    folder_to_mrss_urls = defaultdict(set)
    for gid in sorted(scan['all_ids']):
        probes, urls = _probe_mrss(session, gid)
        mrss_probe_rows.extend(probes)
        for url in urls:
            id_to_mrss_urls[gid].add(url)
            match = GALLERY_PATH_RE.search(urlparse(url).path)
            if match:
                folder = match.group(1)
                scan['id_to_folders'][gid].add(folder)
                folder_to_mrss_urls[folder].add(url)
                for article_url in scan['id_to_articles'].get(gid, set()):
                    scan['folder_to_articles'][folder].add(article_url)
        time.sleep(0.08)

    folder_rows = []
    probe_rows = []
    file_rows = []
    folders = sorted(
        set(scan['folder_to_urls']) |
        set(scan['folder_to_articles']) |
        set(folder_to_mrss_urls)
    )

    for folder in folders:
        probes, indexed_urls, indexable = _probe_folder(session, folder)
        probe_rows.extend(probes)
        explicit_urls = sorted(scan['folder_to_urls'].get(folder, set()))
        mrss_urls = sorted(folder_to_mrss_urls.get(folder, set()))
        enumerated_urls = []
        for url in indexed_urls + mrss_urls:
            _add_unique(enumerated_urls, url)
        urls = []
        for url in enumerated_urls + explicit_urls:
            _add_unique(urls, url)

        downloaded = 0
        failed = 0
        for url in urls:
            dest = output_dir / 'galleries' / safe_slug(folder) / _filename(url)
            result = _download_one(session, url, dest)
            result['folder'] = folder
            file_rows.append(result)
            if result['status'] == 'ok':
                downloaded += 1
            else:
                failed += 1
            time.sleep(0.12)

        ids = sorted(gid for gid, mapped in scan['id_to_folders'].items() if folder in mapped)
        complete_source = indexable or bool(mrss_urls)
        folder_rows.append({
            'folder': folder,
            'gallery_ids': ';'.join(str(x) for x in ids),
            'article_urls': ';'.join(sorted(scan['folder_to_articles'].get(folder, set()))),
            'explicit_count': len(explicit_urls),
            'indexed_count': len(indexed_urls),
            'mrss_count': len(mrss_urls),
            'enumerated_count': len(enumerated_urls),
            'downloaded_count': downloaded,
            'failed_count': failed,
            'indexable': indexable,
            'mrss_available': bool(mrss_urls),
            'status': gallery_status(
                gallery_ids=ids, folders=[folder], explicit_count=len(explicit_urls),
                indexed_count=len(enumerated_urls), downloaded_count=downloaded,
                failed_count=failed, indexable=complete_source,
            ),
        })

    mapping_rows = []
    for gid in sorted(scan['all_ids']):
        mapped = sorted(scan['id_to_folders'].get(gid, set()))
        mapping_rows.append({
            'gallery_id': gid,
            'folders': ';'.join(mapped),
            'mrss_images': len(id_to_mrss_urls.get(gid, set())),
            'status': 'mapped' if mapped else 'unresolved',
        })

    unresolved = [row for row in mapping_rows if row['status'] == 'unresolved']
    _write_csv(output_dir / 'gallery_recovery.csv', folder_rows,
               ['folder','gallery_ids','article_urls','explicit_count','indexed_count','mrss_count','enumerated_count','downloaded_count','failed_count','indexable','mrss_available','status'])
    _write_csv(output_dir / 'gallery_id_mapping.csv', mapping_rows,
               ['gallery_id','folders','mrss_images','status'])
    _write_csv(output_dir / 'unresolved_gallery_ids.csv', unresolved,
               ['gallery_id','folders','mrss_images','status'])
    _write_csv(output_dir / 'folder_probe.csv', probe_rows,
               ['folder','probe_url','status_code','final_url','indexable','images_found','error'])
    _write_csv(output_dir / 'mrss_probe.csv', mrss_probe_rows,
               ['gallery_id','probe_url','status_code','final_url','images_found','error'])
    _write_csv(output_dir / 'gallery_files.csv', file_rows,
               ['folder','status','source_url','resolved_url','path','bytes','error'])

    summary = {
        'articles_with_gallery_evidence': len(scan['articles']),
        'gallery_ids_total': len(scan['all_ids']),
        'gallery_ids_mapped': sum(1 for row in mapping_rows if row['status'] == 'mapped'),
        'gallery_ids_unresolved': len(unresolved),
        'mrss_gallery_ids_resolved': sum(1 for gid in scan['all_ids'] if id_to_mrss_urls.get(gid)),
        'mrss_images_discovered': len({url for urls in id_to_mrss_urls.values() for url in urls}),
        'folders_total': len(folders),
        'folders_indexable': sum(1 for row in folder_rows if row['indexable']),
        'folders_with_mrss': sum(1 for row in folder_rows if row['mrss_available']),
        'folders_complete': sum(1 for row in folder_rows if row['status'] == 'complete'),
        'folders_partial': sum(1 for row in folder_rows if row['status'] == 'partial'),
        'folders_missing': sum(1 for row in folder_rows if row['status'] == 'missing'),
        'files_downloaded': sum(1 for row in file_rows if row['status'] == 'ok'),
        'files_failed': sum(1 for row in file_rows if row['status'] == 'error'),
    }
    (output_dir / 'gallery-summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description='Recover legacy Snowmagazin NextGEN galleries from archived article evidence.')
    parser.add_argument('--archive-root', required=True)
    parser.add_argument('--output', default='gallery_out')
    args = parser.parse_args()
    print(json.dumps(recover_galleries(args.archive_root, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
