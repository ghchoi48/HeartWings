/* Reading and navigation remain available without JavaScript. */
(() => {
  const navigation = document.querySelector('.wiki-navigation');
  const toc = document.querySelector('.wiki-toc');
  const mobile = window.matchMedia('(max-width: 700px)');
  const compact = window.matchMedia('(max-width: 1100px)');
  const syncMenus = () => {
    navigation.open = !mobile.matches;
    toc.open = !compact.matches;
  };
  syncMenus();
  mobile.addEventListener('change', syncMenus);
  compact.addEventListener('change', syncMenus);

  // Never assign src until handlers exist; missing and corrupt files stay hidden.
  document.querySelectorAll('[data-screenshot]').forEach(figure => {
    const img = figure.querySelector('img');
    img.addEventListener('load', () => { figure.hidden = false; }, { once: true });
    img.addEventListener('error', () => { figure.hidden = true; }, { once: true });
    img.src = figure.dataset.screenshot;
  });

  const form = document.querySelector('.wiki-search');
  const input = form.querySelector('input');
  const status = form.querySelector('[role="status"]');
  const results = form.querySelector('.search-results');
  form.hidden = false;
  let index;
  let pending;
  let revision = 0;
  let timer;
  const normalize = text => text.normalize('NFKC').toLocaleLowerCase('ko');
  async function search() {
    const request = ++revision;
    const terms = normalize(input.value).trim().split(/\s+/).filter(Boolean);
    results.replaceChildren();
    if (!terms.length) {
      status.textContent = '';
      return;
    }
    status.textContent = '문서를 찾고 있습니다…';
    try {
      if (!index) {
        if (!pending) {
          pending = fetch(new URL('search-index.json', document.baseURI))
            .then(response => {
              if (!response.ok) throw new Error('Index unavailable');
              return response.json();
            }).then(data => {
              if (!Array.isArray(data)) throw new Error('Invalid index');
              index = data;
              return data;
            }).finally(() => { pending = undefined; });
        }
        await pending;
      }
      if (request !== revision) return;
      const matches = index.map(entry => {
        const title = normalize(`${entry.title} ${entry.heading}`);
        const full = `${title} ${normalize(entry.text)}`;
        return { entry, score: terms.reduce((sum, term) => sum + (title.includes(term) ? 1 : 0), 0),
          matches: terms.every(term => full.includes(term)) };
      }).filter(item => item.matches).sort((a, b) => b.score - a.score);
      status.textContent = matches.length ? `${matches.length}개 항목을 찾았습니다.` : '검색 결과가 없습니다. 짧은 단어로 다시 검색하거나 문서 목록을 확인하세요.';
      for (const { entry } of matches) {
        const item = document.createElement('li');
        const link = document.createElement('a');
        link.href = entry.url;
        link.textContent = `${entry.title} / ${entry.heading}`;
        const snippet = document.createElement('p');
        const found = terms.map(term => normalize(entry.text).indexOf(term)).find(pos => pos >= 0) ?? 0;
        const start = Math.max(0, found - 25);
        snippet.textContent = `${start ? '…' : ''}${entry.text.slice(start, start + 110)}${entry.text.length > start + 110 ? '…' : ''}`;
        item.append(link, snippet);
        results.append(item);
      }
    } catch {
      if (request === revision) status.textContent = '검색을 불러오지 못했습니다. 다시 검색하거나 아래 문서 목록을 이용하세요.';
    }
  }
  input.addEventListener('input', () => {
    ++revision;
    clearTimeout(timer);
    timer = setTimeout(search, 150);
  });
  form.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); search(); });
})();
