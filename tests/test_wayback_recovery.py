from snowmagazin_crawler.wayback_recovery import (
    article_url_variants,
    build_cdx_url,
    select_image_snapshot,
    wayback_raw_url,
)
from snowmagazin_crawler.wayback_assets import (
    wayback_html_replay_candidates,
    wayback_replay_candidates,
)


def test_build_cdx_url_requests_successful_image_snapshots_for_exact_url():
    url = 'http://www.snowmagazin.sk/wp-content/uploads/2014/11/photo.jpg'
    cdx = build_cdx_url(url)
    assert 'web.archive.org/cdx/search/cdx' in cdx
    assert 'url=http%3A%2F%2Fwww.snowmagazin.sk%2Fwp-content%2Fuploads%2F2014%2F11%2Fphoto.jpg' in cdx
    assert 'filter=statuscode%3A200' in cdx
    assert 'output=json' in cdx


def test_select_image_snapshot_prefers_latest_valid_image_capture():
    rows = [
        ['timestamp', 'original', 'mimetype', 'statuscode', 'digest'],
        ['20150101010101', 'http://example/photo.jpg', 'image/jpeg', '200', 'A'],
        ['20170202020202', 'http://example/photo.jpg', 'text/html', '200', 'B'],
        ['20161212000000', 'http://example/photo.jpg', 'image/jpeg', '200', 'C'],
    ]
    snap = select_image_snapshot(rows)
    assert snap['timestamp'] == '20161212000000'
    assert snap['mimetype'] == 'image/jpeg'


def test_wayback_raw_url_uses_id_modifier_to_preserve_original_bytes():
    snap = {
        'timestamp': '20161212000000',
        'original': 'http://www.snowmagazin.sk/wp-content/uploads/2014/11/photo.jpg',
    }
    assert wayback_raw_url(snap) == (
        'https://web.archive.org/web/20161212000000id_/'
        'http://www.snowmagazin.sk/wp-content/uploads/2014/11/photo.jpg'
    )


def test_wayback_replay_candidates_try_raw_then_image_then_standard_replay():
    snap = {
        'timestamp': '20161212000000',
        'original': 'http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg',
    }
    assert wayback_replay_candidates(snap) == [
        'https://web.archive.org/web/20161212000000id_/http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg',
        'https://web.archive.org/web/20161212000000im_/http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg',
        'https://web.archive.org/web/20161212000000/http://www.snowmagazin.sk/wp-content/gallery/elbrus/01.jpg',
    ]


def test_wayback_html_replay_candidates_try_raw_then_standard_replay():
    snap = {
        'timestamp': '20141011165619',
        'original': 'http://www.snowmagazin.sk/2009/10/zimny-vystup-na-elbrus-nie-je-vylet-do-rakuskych-stredisk/',
    }
    assert wayback_html_replay_candidates(snap) == [
        'https://web.archive.org/web/20141011165619id_/http://www.snowmagazin.sk/2009/10/zimny-vystup-na-elbrus-nie-je-vylet-do-rakuskych-stredisk/',
        'https://web.archive.org/web/20141011165619/http://www.snowmagazin.sk/2009/10/zimny-vystup-na-elbrus-nie-je-vylet-do-rakuskych-stredisk/',
    ]


def test_article_url_variants_include_legacy_wp_post_id_permalink():
    variants = article_url_variants(
        'https://snowmagazin.relaxmagazin.sk/appka-hzs-umoznuje-lokalizaciu-aj-nudzovu-sms/',
        '2015-11-18T00:00:00',
        post_id=11225,
    )
    assert 'http://www.snowmagazin.sk/?p=11225' in variants
    assert 'https://www.snowmagazin.sk/?p=11225' in variants
    assert 'http://snowmagazin.sk/?p=11225' in variants
    assert 'https://snowmagazin.sk/?p=11225' in variants
