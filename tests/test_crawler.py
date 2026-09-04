import csv

from snowmagazin_crawler.crawler import crawl, extract_article_from_html


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text='', headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.headers = {}

    def get(self, url, **kwargs):
        params = kwargs.get('params') or {}
        key = (url, tuple(sorted(params.items())))
        if key in self.mapping:
            return self.mapping[key]
        if url in self.mapping:
            response = self.mapping[url]
            if isinstance(response, Exception):
                raise response
            return response
        return FakeResponse(status_code=404)


def test_extract_article_from_html_uses_entry_content_and_metadata():
    url = 'https://snowmagazin.relaxmagazin.sk/stary-clanok/'
    html = '''
    <html><head>
      <link rel="canonical" href="https://snowmagazin.relaxmagazin.sk/stary-clanok/" />
      <meta property="article:published_time" content="2010-02-20T08:30:00+01:00" />
      <meta name="author" content="Igor Plávka" />
    </head><body>
      <article>
        <h1 class="entry-title">Starý článok</h1>
        <div class="entry-content"><p>Publikovaný <strong>text</strong>.</p>[nggallery id=7]</div>
      </article>
    </body></html>
    '''
    article = extract_article_from_html(url, html)
    assert article['title'] == 'Starý článok'
    assert article['url'] == url
    assert article['published_date'].startswith('2010-02-20')
    assert article['author_name'] == 'Igor Plávka'
    assert article['text'] == 'Publikovaný text.'
    assert article['nggallery_ids'] == [7]
    assert article['source_method'] == 'html_fallback'


def test_crawl_archives_rest_posts_skips_duplicate_url_and_records_fallback_error(tmp_path):
    base = 'https://snowmagazin.relaxmagazin.sk'
    endpoint = base + '/wp-json/wp/v2/posts'
    rest_post = {
        'id': 1,
        'date': '2010-01-01T10:00:00',
        'modified': '2010-01-02T10:00:00',
        'link': base + '/one/',
        'slug': 'one',
        'title': {'rendered': 'One'},
        'excerpt': {'rendered': '<p>First</p>'},
        'content': {'rendered': '<p>REST body</p>'},
        'author': 4,
        'categories': [],
        'tags': [],
    }
    root_html = '''
      <a href="/one/">duplicate REST</a>
      <a href="/two/">fallback</a>
      <a href="/broken/">broken</a>
    '''
    fallback_html = '''
      <html><head><meta property="article:published_time" content="2010-02-03T12:00:00+01:00"></head>
      <body><article><h1>Two</h1><div class="entry-content"><p>Fallback body</p></div></article></body></html>
    '''
    session = FakeSession({
        (endpoint, (('page', 1), ('per_page', 100))): FakeResponse(json_data=[rest_post], headers={'X-WP-TotalPages': '1'}),
        base + '/wp-sitemap.xml': FakeResponse(status_code=404),
        base + '/post-sitemap.xml': FakeResponse(status_code=404),
        base + '/sitemap_index.xml': FakeResponse(status_code=404),
        base + '/': FakeResponse(text=root_html),
        base + '/two/': FakeResponse(text=fallback_html),
        base + '/broken/': FakeResponse(status_code=500),
    })

    summary = crawl(session=session, base_url=base, output_dir=tmp_path, delay=0)
    assert summary['ok'] == 2
    assert summary['errors'] == 1
    assert summary['total_rows'] == 3
    assert (tmp_path / 'archive' / '2010' / '2010-01-01-one' / 'published.txt').read_text() == 'REST body'
    assert (tmp_path / 'archive' / '2010' / '2010-02-03-two' / 'published.txt').read_text() == 'Fallback body'
    with (tmp_path / 'articles.csv').open(newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    broken = next(row for row in rows if row['url'].endswith('/broken/'))
    assert broken['status'] == 'error'
