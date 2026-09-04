from pathlib import Path
from urllib.parse import urlparse

import requests

from .media import _looks_like_image

WAYBACK_BASE = 'https://web.archive.org/web'


def wayback_replay_candidates(snapshot):
    timestamp = snapshot['timestamp']
    original = snapshot['original']
    return [
        f'{WAYBACK_BASE}/{timestamp}id_/{original}',
        f'{WAYBACK_BASE}/{timestamp}im_/{original}',
        f'{WAYBACK_BASE}/{timestamp}/{original}',
    ]


def wayback_html_replay_candidates(snapshot):
    timestamp = snapshot['timestamp']
    original = snapshot['original']
    return [
        f'{WAYBACK_BASE}/{timestamp}id_/{original}',
        f'{WAYBACK_BASE}/{timestamp}/{original}',
    ]


def gallery_relative_path(original):
    path = urlparse(original).path
    marker = '/wp-content/gallery/'
    if marker not in path.lower():
        return ''
    start = path.lower().index(marker) + len(marker)
    return path[start:].lstrip('/')


def download_wayback_image(session, snapshot, destination, timeout=60):
    destination = Path(destination)
    errors = []
    for replay_url in wayback_replay_candidates(snapshot):
        try:
            response = session.get(replay_url, timeout=timeout, allow_redirects=True)
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            continue
        if response.status_code >= 400:
            errors.append(f'HTTP {response.status_code}')
            continue
        if not _looks_like_image(response.content, response.headers.get('Content-Type', '')):
            errors.append(f'not-image {response.headers.get("Content-Type", "")}'.strip())
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return {
            'status': 'ok',
            'resolved_url': replay_url,
            'bytes': len(response.content),
            'error': '',
        }
    return {
        'status': 'error',
        'resolved_url': '',
        'bytes': 0,
        'error': '; '.join(errors[-3:]),
    }
