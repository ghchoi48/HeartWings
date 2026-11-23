"""Ctrl+클릭으로 본문의 링크를 열 수 있는 편집기."""

from nicegui import ui


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
    ui.run_javascript(INSTALL_LINK_CURSOR)
    editor = ui.editor(*args, **kwargs).classes('ctrl-link-editor')
    editor.on('click', js_handler=OPEN_LINK_ON_CTRL_CLICK)
    return editor
