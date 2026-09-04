from snowmagazin_crawler.core import (
    extract_gallery_ids,
    html_to_text,
    safe_slug,
    normalize_wp_post,
    is_article_url,
)


def test_extract_gallery_ids_handles_quoted_and_unquoted_ids():
    html = '<p>x</p>[nggallery id=7][nggallery id="148"][nggallery id=7]'
    assert extract_gallery_ids(html) == [7, 148]


def test_html_to_text_removes_markup_and_shortcodes():
    html = '<p>Hello <strong>world</strong>.</p>[nggallery id=27]<p>Next&nbsp;line</p>'
    assert html_to_text(html) == 'Hello world.\nNext line'


def test_safe_slug_normalizes_accents_spaces_and_symbols():
    assert safe_slug('Žltý sneh / test') == 'zlty-sneh-test'
    assert safe_slug('  Ahoj---Svet  ') == 'ahoj-svet'


def test_normalize_wp_post_preserves_published_content_and_metadata():
    post = {
        'id': 123,
        'date': '2010-12-07T13:07:11',
        'modified': '2011-01-01T10:00:00',
        'link': 'https://snowmagazin.relaxmagazin.sk/example/',
        'slug': 'example',
        'title': {'rendered': 'Example &amp; test'},
        'excerpt': {'rendered': '<p>Perex</p>'},
        'content': {'rendered': '<p>Hello <strong>world</strong>.</p>[nggallery id=27]'},
        'author': 4,
        'categories': [2, 3],
        'tags': [9],
    }
    article = normalize_wp_post(post)
    assert article['id'] == 123
    assert article['published_date'] == '2010-12-07T13:07:11'
    assert article['url'].endswith('/example/')
    assert article['title'] == 'Example & test'
    assert article['excerpt_text'] == 'Perex'
    assert article['html'].startswith('<p>Hello')
    assert article['text'] == 'Hello world.'
    assert article['nggallery_ids'] == [27]
    assert article['source_method'] == 'wp_rest'


def test_is_article_url_rejects_taxonomy_admin_pagination_and_foreign_urls():
    good = 'https://snowmagazin.relaxmagazin.sk/slovenskym-vlakom-za-rakuskym-snehom/'
    assert is_article_url(good)
    bad = [
        'https://snowmagazin.relaxmagazin.sk/',
        'https://snowmagazin.relaxmagazin.sk/wp-admin/',
        'https://snowmagazin.relaxmagazin.sk/wp-json/wp/v2/posts',
        'https://snowmagazin.relaxmagazin.sk/kategoria/strediska/',
        'https://snowmagazin.relaxmagazin.sk/znacka/freeride/',
        'https://snowmagazin.relaxmagazin.sk/tag/freeride/',
        'https://snowmagazin.relaxmagazin.sk/author/redakcia/',
        'https://snowmagazin.relaxmagazin.sk/page/2/',
        'https://snowmagazin.relaxmagazin.sk/feed/',
        'https://example.com/foo/',
    ]
    assert all(not is_article_url(url) for url in bad)


def test_normalize_wp_post_uses_embedded_author_and_term_names_when_available():
    post = {
        'id': 77,
        'date': '2011-01-01T00:00:00',
        'link': 'https://snowmagazin.relaxmagazin.sk/embedded/',
        'slug': 'embedded',
        'title': {'rendered': 'Embedded'},
        'excerpt': {'rendered': ''},
        'content': {'rendered': '<p>Body</p>'},
        'author': 8,
        'categories': [2],
        'tags': [9],
        '_embedded': {
            'author': [{'id': 8, 'name': 'Marek Parajka'}],
            'wp:term': [
                [{'id': 2, 'name': 'Freeride', 'taxonomy': 'category'}],
                [{'id': 9, 'name': 'Jasná', 'taxonomy': 'post_tag'}],
            ],
        },
    }
    article = normalize_wp_post(post)
    assert article['author_name'] == 'Marek Parajka'
    assert article['categories'] == ['Freeride']
    assert article['tags'] == ['Jasná']
