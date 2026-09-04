import csv
import json

from snowmagazin_crawler.archive import article_key, write_article, write_manifest


def sample_article(**overrides):
    article = {
        'id': 123,
        'published_date': '2010-12-07T13:07:11',
        'modified_date': '2010-12-08T10:00:00',
        'url': 'https://snowmagazin.relaxmagazin.sk/example/',
        'slug': 'example',
        'title': 'Example',
        'excerpt_html': '<p>Perex</p>',
        'excerpt_text': 'Perex',
        'html': '<p>Hello</p>',
        'text': 'Hello',
        'author_id': 4,
        'author_name': 'Redakcia',
        'categories': [2],
        'tags': [9],
        'nggallery_ids': [27],
        'media_urls': ['http://www.snowmagazin.sk/wp-content/gallery/x/1.jpg'],
        'source_method': 'wp_rest',
    }
    article.update(overrides)
    return article


def test_article_key_prefers_id_then_url_then_slug():
    assert article_key(sample_article()) == 'id:123'
    assert article_key(sample_article(id=None)) == 'url:https://snowmagazin.relaxmagazin.sk/example/'
    assert article_key(sample_article(id=None, url=None, slug='fallback')) == 'slug:fallback'


def test_write_article_creates_year_date_slug_folder_and_files(tmp_path):
    row = write_article(sample_article(), tmp_path)
    folder = tmp_path / 'archive' / '2010' / '2010-12-07-example'
    assert folder.is_dir()
    assert (folder / 'published.html').read_text() == '<p>Hello</p>'
    assert (folder / 'published.txt').read_text() == 'Hello'
    metadata = json.loads((folder / 'metadata.json').read_text())
    assert metadata['title'] == 'Example'
    assert 'html' not in metadata
    assert 'text' not in metadata
    assert row['archive_path'] == 'archive/2010/2010-12-07-example'
    assert row['status'] == 'ok'


def test_write_manifest_serializes_lists_and_errors(tmp_path):
    rows = [{
        'id': 123, 'title': 'Example', 'url': 'https://snowmagazin.relaxmagazin.sk/example/',
        'published_date': '2010-12-07T13:07:11', 'year': '2010', 'slug': 'example',
        'author_id': 4, 'author_name': 'Redakcia', 'categories': [2, 3], 'tags': [9],
        'nggallery_ids': [27], 'media_urls': ['a.jpg', 'b.jpg'], 'source_method': 'wp_rest',
        'archive_path': 'archive/2010/2010-12-07-example', 'status': 'ok', 'error': '',
    }]
    path = tmp_path / 'articles.csv'
    write_manifest(rows, path)
    with path.open(newline='', encoding='utf-8') as fh:
        data = list(csv.DictReader(fh))
    assert data[0]['categories'] == '2;3'
    assert data[0]['nggallery_ids'] == '27'
    assert data[0]['media_urls'] == 'a.jpg;b.jpg'
