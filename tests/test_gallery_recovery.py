from snowmagazin_crawler.gallery_recovery import (
    extract_gallery_evidence,
    extract_index_images,
    extract_mrss_images,
    gallery_status,
)
from snowmagazin_crawler.wayback_recovery import (
    extract_wayback_snapshot_folders,
    parse_cdx_rows,
)


def test_extract_gallery_evidence_maps_shortcode_to_legacy_folder():
    html = '''
    <p>Text</p>
    [nggallery id=86]
    <img src="http://www.snowmagazin.sk/wp-content/gallery/obergurgl-2010/5.jpg">
    <a href="/wp-content/gallery/obergurgl-2010/6.jpg">foto</a>
    '''
    evidence = extract_gallery_evidence(
        html,
        'https://snowmagazin.relaxmagazin.sk/obergurgl/',
        metadata_ids=[86],
    )
    assert evidence['gallery_ids'] == [86]
    assert evidence['folders'] == ['obergurgl-2010']
    assert evidence['id_folder_pairs'] == [(86, 'obergurgl-2010')]
    assert any(url.endswith('/wp-content/gallery/obergurgl-2010/5.jpg') for url in evidence['explicit_urls'])
    assert any(url.endswith('/wp-content/gallery/obergurgl-2010/6.jpg') for url in evidence['explicit_urls'])


def test_extract_index_images_returns_originals_and_skips_parent_and_thumbs():
    html = '''
    <html><body><h1>Index of /wp-content/gallery/test/</h1>
      <a href="../">Parent Directory</a>
      <a href="1.jpg">1.jpg</a>
      <a href="two.JPG">two.JPG</a>
      <a href="thumbs/">thumbs/</a>
      <a href="notes.txt">notes.txt</a>
    </body></html>
    '''
    urls = extract_index_images(
        html,
        'https://snowmagazin.relaxmagazin.sk/wp-content/gallery/test/',
    )
    assert urls == [
        'https://snowmagazin.relaxmagazin.sk/wp-content/gallery/test/1.jpg',
        'https://snowmagazin.relaxmagazin.sk/wp-content/gallery/test/two.JPG',
    ]


def test_extract_mrss_images_recovers_full_gallery_urls_and_ignores_thumbnails():
    xml = '''<?xml version="1.0"?>
    <rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item>
      <media:content url="http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg" type="image/jpeg" />
      <media:thumbnail url="http://www.snowmagazin.sk/wp-content/gallery/elbrus/thumbs/thumbs_01.jpg" />
      <enclosure url="http://www.snowmagazin.sk/wp-content/gallery/elbrus/02.jpg" type="image/jpeg" />
    </item></channel></rss>'''
    urls = extract_mrss_images(xml, 'https://snowmagazin.relaxmagazin.sk/')
    assert urls == [
        'http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg',
        'http://www.snowmagazin.sk/wp-content/gallery/elbrus/02.jpg',
    ]


def test_parse_cdx_rows_returns_unique_original_urls_and_timestamps():
    payload = '''
    urlkey timestamp original mimetype statuscode digest length
    sk,magazin)/wp-content/gallery/elbrus/a.jpg 20110102030405 http://www.snowmagazin.sk/wp-content/gallery/elbrus/a.jpg image/jpeg 200 ABC 123
    sk,magazin)/wp-content/gallery/elbrus/a.jpg 20120102030405 http://www.snowmagazin.sk/wp-content/gallery/elbrus/a.jpg image/jpeg 200 DEF 123
    sk,magazin)/wp-content/gallery/elbrus/thumbs/thumbs_a.jpg 20110102030405 http://www.snowmagazin.sk/wp-content/gallery/elbrus/thumbs/thumbs_a.jpg image/jpeg 200 GHI 20
    '''
    rows = parse_cdx_rows(payload)
    assert rows == [
        {
            'timestamp': '20110102030405',
            'original': 'http://www.snowmagazin.sk/wp-content/gallery/elbrus/a.jpg',
            'mimetype': 'image/jpeg',
            'statuscode': '200',
        },
        {
            'timestamp': '20110102030405',
            'original': 'http://www.snowmagazin.sk/wp-content/gallery/elbrus/thumbs/thumbs_a.jpg',
            'mimetype': 'image/jpeg',
            'statuscode': '200',
        },
    ]


def test_extract_wayback_snapshot_folders_recovers_rendered_nextgen_folder():
    html = '''
    <html><body>
      <div class="ngg-galleryoverview" id="ngg-gallery-148-1">
        <a href="http://www.snowmagazin.sk/wp-content/gallery/fwt-russia-usa/01.jpg">one</a>
        <img src="http://www.snowmagazin.sk/wp-content/gallery/fwt-russia-usa/thumbs/thumbs_01.jpg">
      </div>
    </body></html>
    '''
    assert extract_wayback_snapshot_folders(html) == ['fwt-russia-usa']


def test_gallery_status_is_partial_when_only_explicit_files_survive_without_index():
    status = gallery_status(
        gallery_ids=[86],
        folders=['obergurgl-2010'],
        explicit_count=2,
        indexed_count=0,
        downloaded_count=2,
        failed_count=0,
        indexable=False,
    )
    assert status == 'partial'


def test_gallery_status_is_complete_when_directory_index_was_enumerated_without_failures():
    status = gallery_status(
        gallery_ids=[86],
        folders=['obergurgl-2010'],
        explicit_count=2,
        indexed_count=18,
        downloaded_count=18,
        failed_count=0,
        indexable=True,
    )
    assert status == 'complete'


def test_gallery_status_is_unresolved_for_shortcode_without_folder_or_files():
    status = gallery_status(
        gallery_ids=[7],
        folders=[],
        explicit_count=0,
        indexed_count=0,
        downloaded_count=0,
        failed_count=0,
        indexable=False,
    )
    assert status == 'unresolved'
