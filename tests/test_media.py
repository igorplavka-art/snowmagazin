from pathlib import Path

from snowmagazin_crawler.media import (
    extract_page_media,
    media_candidates,
    download_media,
    summarize_gallery,
)


class FakeResponse:
    def __init__(self, status_code=200, content=b'', headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.mapping.get(url, FakeResponse(status_code=404))


def test_media_candidates_prefers_original_size_on_current_mirror():
    url = 'http://www.snowmagazin.sk/wp-content/uploads/2015/11/photo-600x400.jpg'
    candidates = media_candidates(url, 'https://snowmagazin.relaxmagazin.sk')
    assert candidates[0] == 'https://snowmagazin.relaxmagazin.sk/wp-content/uploads/2015/11/photo.jpg'
    assert 'https://snowmagazin.relaxmagazin.sk/wp-content/uploads/2015/11/photo-600x400.jpg' in candidates
    assert url in candidates


def test_extract_page_media_keeps_article_images_and_gallery_files_but_not_sidebar():
    page_url = 'https://snowmagazin.relaxmagazin.sk/clanok/'
    html = '''
    <html><body>
      <div class="tag-styles">
        <img src="/wp-content/uploads/2011/01/article.jpg"
             srcset="/wp-content/uploads/2011/01/article-300x200.jpg 300w, /wp-content/uploads/2011/01/article.jpg 1200w">
        <div class="ngg-gallery-thumbnail-box"><a href="/wp-content/gallery/obergurgl-2010/5.jpg"><img src="/wp-content/gallery/obergurgl-2010/thumbs/thumbs_5.jpg"></a></div>
      </div>
      <aside><img src="/wp-content/uploads/2026/sidebar.jpg"></aside>
    </body></html>
    '''
    found = extract_page_media(html, page_url)
    urls = found['urls']
    assert 'https://snowmagazin.relaxmagazin.sk/wp-content/uploads/2011/01/article.jpg' in urls
    assert 'https://snowmagazin.relaxmagazin.sk/wp-content/gallery/obergurgl-2010/5.jpg' in urls
    assert 'https://snowmagazin.relaxmagazin.sk/wp-content/uploads/2026/sidebar.jpg' not in urls
    assert found['gallery_folders'] == ['obergurgl-2010']


def test_download_media_uses_fallback_candidate_and_validates_image(tmp_path):
    original = 'http://www.snowmagazin.sk/wp-content/uploads/2015/11/photo.jpg'
    mirror = 'https://snowmagazin.relaxmagazin.sk/wp-content/uploads/2015/11/photo.jpg'
    session = FakeSession({
        mirror: FakeResponse(200, b'\xff\xd8\xfftestjpeg', {'Content-Type': 'image/jpeg'}),
        original: FakeResponse(404),
    })
    result = download_media(session, original, tmp_path / 'photo.jpg', base_url='https://snowmagazin.relaxmagazin.sk')
    assert result['status'] == 'ok'
    assert result['resolved_url'] == mirror
    assert (tmp_path / 'photo.jpg').read_bytes().startswith(b'\xff\xd8\xff')


def test_summarize_gallery_marks_partial_when_any_file_failed():
    row = summarize_gallery(
        article_url='https://snowmagazin.relaxmagazin.sk/clanok/',
        gallery_ids=[7],
        folders=['obergurgl-2010'],
        media_results=[
            {'status': 'ok', 'gallery_folder': 'obergurgl-2010'},
            {'status': 'error', 'gallery_folder': 'obergurgl-2010'},
        ],
    )
    assert row['status'] == 'partial'
    assert row['downloaded_count'] == 1
    assert row['failed_count'] == 1
