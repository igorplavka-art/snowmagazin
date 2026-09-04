from snowmagazin_crawler.discovery import iter_wp_posts, discover_article_urls


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text='', headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, **kwargs):
        params = kwargs.get('params') or {}
        key = (url, tuple(sorted(params.items())))
        self.calls.append(key)
        if key in self.mapping:
            return self.mapping[key]
        if url in self.mapping:
            return self.mapping[url]
        return FakeResponse(status_code=404)


def test_iter_wp_posts_paginates_and_respects_limit():
    base = 'https://snowmagazin.relaxmagazin.sk'
    endpoint = base + '/wp-json/wp/v2/posts'
    session = FakeSession({
        (endpoint, (('page', 1), ('per_page', 100))): FakeResponse(json_data=[{'id': 1}, {'id': 2}], headers={'X-WP-TotalPages': '2'}),
        (endpoint, (('page', 2), ('per_page', 100))): FakeResponse(json_data=[{'id': 3}], headers={'X-WP-TotalPages': '2'}),
    })
    assert [p['id'] for p in iter_wp_posts(session, base)] == [1, 2, 3]
    assert [p['id'] for p in iter_wp_posts(session, base, limit=2)] == [1, 2]


def test_discover_article_urls_reads_sitemap_index_and_child_sitemap():
    base = 'https://snowmagazin.relaxmagazin.sk'
    session = FakeSession({
        base + '/wp-sitemap.xml': FakeResponse(text='''<?xml version="1.0"?><sitemapindex>
          <sitemap><loc>https://snowmagazin.relaxmagazin.sk/wp-sitemap-posts-post-1.xml</loc></sitemap>
        </sitemapindex>'''),
        base + '/wp-sitemap-posts-post-1.xml': FakeResponse(text='''<?xml version="1.0"?><urlset>
          <url><loc>https://snowmagazin.relaxmagazin.sk/prvy-clanok/</loc></url>
          <url><loc>https://snowmagazin.relaxmagazin.sk/kategoria/strediska/</loc></url>
          <url><loc>https://snowmagazin.relaxmagazin.sk/druhy-clanok/</loc></url>
        </urlset>'''),
        base + '/': FakeResponse(text=''),
    })
    urls = discover_article_urls(session, base, max_pages=3)
    assert urls == [
        'https://snowmagazin.relaxmagazin.sk/druhy-clanok/',
        'https://snowmagazin.relaxmagazin.sk/prvy-clanok/',
    ]


def test_discover_article_urls_follows_category_pagination_and_deduplicates():
    base = 'https://snowmagazin.relaxmagazin.sk'
    session = FakeSession({
        base + '/wp-sitemap.xml': FakeResponse(status_code=404),
        base + '/post-sitemap.xml': FakeResponse(status_code=404),
        base + '/sitemap_index.xml': FakeResponse(status_code=404),
        base + '/': FakeResponse(text='''
          <a href="/kategoria/strediska/">Strediska</a>
          <a href="/jeden/">Jeden</a>
        '''),
        base + '/kategoria/strediska/': FakeResponse(text='''
          <a href="https://snowmagazin.relaxmagazin.sk/jeden/">Jeden</a>
          <a href="/dva/">Dva</a>
          <a href="/kategoria/strediska/page/2/">Next</a>
        '''),
        base + '/kategoria/strediska/page/2/': FakeResponse(text='''
          <a href="/tri/">Tri</a>
          <a href="/jeden/">Jeden again</a>
        '''),
    })
    assert discover_article_urls(session, base, max_pages=10) == [
        base + '/dva/', base + '/jeden/', base + '/tri/'
    ]
