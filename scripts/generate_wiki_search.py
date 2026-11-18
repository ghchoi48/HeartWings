"""Build the public wiki search index from its static HTML (stdlib only)."""

import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / 'website' / 'wiki'


class WikiParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.heading = None
        self.title = ''
        self.sections = []
        self.current = None
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article':
            self.in_article = True
        if not self.in_article:
            return
        if tag in ('figure', 'script', 'style'):
            self.ignored += 1
        if self.ignored:
            return
        if tag == 'h1':
            self.heading = 'title'
        elif tag == 'h2':
            self.current = {'anchor': attrs['id'], 'heading': '', 'parts': []}
            self.sections.append(self.current)
            self.heading = 'section'

    def handle_endtag(self, tag):
        if tag in ('figure', 'script', 'style') and self.ignored:
            self.ignored -= 1
        if tag in ('h1', 'h2'):
            self.heading = None
        if tag == 'article':
            self.in_article = False

    def handle_data(self, data):
        if not self.in_article or self.ignored:
            return
        if self.heading == 'title':
            self.title += data
        elif self.heading == 'section':
            self.current['heading'] += data
        elif self.current:
            self.current['parts'].append(data)


def build_index(directory=WIKI):
    entries = []
    for path in sorted(directory.glob('*.html')):
        parser = WikiParser()
        parser.feed(path.read_text(encoding='utf-8'))
        for section in parser.sections:
            entries.append({
                'title': parser.title.strip(),
                'heading': section['heading'].strip(),
                'url': f"{path.name}#{section['anchor']}",
                'text': ' '.join(' '.join(section['parts']).split()),
            })
    return entries


if __name__ == '__main__':
    entries = build_index()
    (WIKI / 'search-index.json').write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Indexed {len(entries)} wiki sections.')
