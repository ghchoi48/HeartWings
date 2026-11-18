"""Check static wiki links, anchors, optional screenshots and search freshness."""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from generate_wiki_search import build_index

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'website'


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids = []
        self.links = []
        self.screenshots = []
        self.feed(path.read_text(encoding='utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])
        if 'data-screenshot' in attrs:
            assert tag == 'figure' and 'hidden' in attrs, 'Optional screenshot must start hidden'
            self.screenshots.append(attrs['data-screenshot'])


def check():
    documents = {p.resolve(): Document(p) for p in SITE.rglob('*.html')}
    count = 0
    shots = set()
    for path, doc in documents.items():
        assert len(doc.ids) == len(set(doc.ids)), f'Duplicate IDs in {path}'
        optional = {(path.parent / name).resolve() for name in doc.screenshots}
        shots.update(optional)
        for value in doc.links:
            url = urlsplit(value)
            if url.scheme or url.netloc:
                continue
            assert not url.path.startswith('/'), f'Root-relative link: {value}'
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target in optional:
                assert target.parent == (SITE / 'assets/wiki').resolve()
                continue
            if target.is_dir():
                target /= 'index.html'
            assert target.is_file(), f'Missing link in {path.name}: {value}'
            if url.fragment and target in documents:
                assert unquote(url.fragment) in documents[target].ids, f'Missing anchor: {value}'
            count += 1
    assert len(shots) == 12, f'Expected 12 screenshot slots, found {len(shots)}'
    index = json.loads((SITE / 'wiki/search-index.json').read_text(encoding='utf-8'))
    assert index == build_index(), 'Search index stale: run generate_wiki_search.py'
    for entry in index:
        filename, anchor = entry['url'].split('#')
        assert anchor in documents[(SITE / 'wiki' / filename).resolve()].ids
        assert entry['text'], f'Empty search entry: {entry["url"]}'
    for query in ('백업', '집단 상담', '학년도', '백업 비밀번호'):
        assert any(all(term in f'{e["title"]} {e["heading"]} {e["text"]}' for term in query.split()) for e in index), query
    assert not any('존재하지않는검색어98765' in e['text'] for e in index)
    sitemap = ET.parse(SITE / 'sitemap.xml')
    urls = {e.text for e in sitemap.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')}
    for path in (SITE / 'wiki').glob('*.html'):
        suffix = '' if path.name == 'index.html' else path.name
        assert 'https://ghchoi48.github.io/HeartWings/wiki/' + suffix in urls
    print(f'PASS: {count} local links, {len(index)} search sections, 12 optional screenshots, sitemap.')


if __name__ == '__main__':
    check()
