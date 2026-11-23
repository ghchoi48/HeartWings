"""단계별 목록 서식과 Ctrl+클릭 링크 열기를 지원하는 편집기."""

from nicegui import ui


ORDERED_LIST_CSS = '''
@counter-style editor-hangul {
    system: alphabetic;
    symbols: '가' '나' '다' '라' '마' '바' '사' '아' '자' '차' '카' '타' '파' '하';
    suffix: '. ';
}
@counter-style editor-decimal-paren {
    system: extends decimal;
    suffix: ') ';
}
@counter-style editor-hangul-paren {
    system: extends editor-hangul;
    suffix: ') ';
}
@counter-style editor-decimal-wrapped {
    system: extends decimal;
    prefix: '(';
    suffix: ') ';
}
@counter-style editor-hangul-wrapped {
    system: extends editor-hangul;
    prefix: '(';
    suffix: ') ';
}
@counter-style editor-circled-decimal {
    system: fixed;
    symbols: '①' '②' '③' '④' '⑤' '⑥' '⑦' '⑧' '⑨' '⑩'
             '⑪' '⑫' '⑬' '⑭' '⑮' '⑯' '⑰' '⑱' '⑲' '⑳';
    suffix: ' ';
}
@counter-style editor-circled-hangul {
    system: fixed;
    symbols: '㉮' '㉯' '㉰' '㉱' '㉲' '㉳' '㉴' '㉵' '㉶' '㉷' '㉸' '㉹' '㉺' '㉻';
    suffix: ' ';
}
'''

# 번호 목록 조상 수로 깊이를 구한다. 브라우저가 만든 중첩 목록도 그대로 지원한다.
for _depth, _counter in enumerate((
    'decimal', 'editor-hangul', 'editor-decimal-paren', 'editor-hangul-paren',
    'editor-decimal-wrapped', 'editor-hangul-wrapped',
    'editor-circled-decimal', 'editor-circled-hangul',
), 1):
    ORDERED_LIST_CSS += (
        '.ctrl-link-editor .q-editor__content ' + 'ol ' * _depth
        + '{ list-style-type: ' + _counter + '; }\n'
    )


UNORDERED_LIST_CSS = ''
for _depth, _bullet in enumerate(('□', '○', '●', '▪'), 1):
    UNORDERED_LIST_CSS += (
        '.ctrl-link-editor .q-editor__content ' + 'ul ' * _depth
        + '{ list-style-type: "' + _bullet + ' "; }\n'
    )


INSTALL_LINK_CURSOR = '''(() => {
    if (document.getElementById('editor-ctrl-link-cursor')) return;
    const style = document.createElement('style');
    style.id = 'editor-ctrl-link-cursor';
    style.textContent = `
        html.editor-ctrl-pressed .ctrl-link-editor .q-editor__content a[href],
        html.editor-ctrl-pressed .ctrl-link-editor .q-editor__content a[href] * {
            cursor: pointer !important;
        }
    `;
    document.head.appendChild(style);

    const update = event => {
        document.documentElement.classList.toggle('editor-ctrl-pressed', event.ctrlKey);
    };
    const reset = () => document.documentElement.classList.remove('editor-ctrl-pressed');
    document.addEventListener('keydown', update, true);
    document.addEventListener('keyup', update, true);
    document.addEventListener('pointermove', update, true);
    window.addEventListener('blur', reset);
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) reset();
    });
})();'''


OPEN_LINK_ON_CTRL_CLICK = '''event => {
    if (!event.ctrlKey || event.button !== 0) return;
    const link = event.target.closest?.('.q-editor__content a[href]');
    if (!link || !event.currentTarget.contains(link)) return;

    event.preventDefault();
    event.stopPropagation();
    let url;
    try {
        url = new URL(link.getAttribute('href'), document.baseURI);
    } catch {
        return;
    }
    if (!['http:', 'https:', 'mailto:', 'tel:'].includes(url.protocol)) return;
    window.open(url.href, '_blank', 'noopener,noreferrer');
}'''


def rich_text_editor(*args, **kwargs) -> ui.editor:
    ui.add_css(ORDERED_LIST_CSS + UNORDERED_LIST_CSS)
    ui.run_javascript(INSTALL_LINK_CURSOR)
    editor = ui.editor(*args, **kwargs).classes('ctrl-link-editor')
    editor.on('click', js_handler=OPEN_LINK_ON_CTRL_CLICK)
    return editor
