"""클라이언트별 메모리 전용 첨부파일 열람창."""
from pathlib import Path
from html import escape
from threading import Event
from weakref import WeakKeyDictionary

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.attachment_preview import render_document

_previews = WeakKeyDictionary()


def close_previews(client):
    for preview in tuple(_previews.get(client, ())):
        preview.close()


class PreviewDialog(ui.dialog):
    def _handle_delete(self):
        self.preview.close(delete_dialog=False)
        super()._handle_delete()


class AttachmentPreview:
    def __init__(self, repository, entry, lock):
        self.repository, self.entry, self.lock = repository, entry, lock
        self.client = ui.context.client
        self.content = b''
        self.cancelled = Event()
        self.images = []
        self.hand_mode = True
        self.is_pdf = Path(entry.filename).suffix.lower() == '.pdf'
        self.filename = entry.filename
        self.page, self.pages, self.zoom = 1, 1, 100
        self.fit, self.busy, self.closed = True, False, False
        if self.client not in _previews:
            _previews[self.client] = set()
            self.client.on_disconnect(close_previews)
            self.client.on_delete(close_previews)
        _previews[self.client].add(self)
        with PreviewDialog().props('persistent') as self.dialog:
            self.dialog.preview = self
            with ui.card().classes('w-full max-w-none gap-0').style('width:94vw; height:92dvh') as self.viewer_card:
                with ui.row().classes('w-full items-center flex-nowrap mb-3'):
                    ui.label(self.filename).classes('grow min-w-0 break-all font-bold')
                    ui.button('닫기', on_click=self.close).props('flat')
                with ui.element('q-toolbar').props('role="toolbar" aria-label="첨부파일 열람 도구"').classes(
                        'w-full gap-2 rounded-t border border-slate-200 overflow-x-auto shrink-0'):
                    with ui.row().props('role="group" aria-label="페이지 이동"').classes(
                            'items-center flex-nowrap gap-1 shrink-0') as self.page_tools:
                        self.previous = ui.button(icon='chevron_left', on_click=lambda: self.change_page(self.page - 1)).props('flat round dense aria-label="이전 페이지"').tooltip('이전 페이지')
                        self.number = ui.number(value=1, min=1, max=1, step=1, precision=0).props(
                            'dense outlined hide-bottom-space hide-arrows aria-label="페이지" input-class="text-center"').classes('w-16')
                        self.number.on('keydown.enter', lambda: self.change_page(self.number.value))
                        self.number.tooltip('페이지 번호 입력 후 Enter로 이동')
                        self.total = ui.label('/ 1').classes('text-sm tabular-nums whitespace-nowrap px-1')
                        self.next = ui.button(icon='chevron_right', on_click=lambda: self.change_page(self.page + 1)).props('flat round dense aria-label="다음 페이지"').tooltip('다음 페이지')
                    self.toolbar_separator = ui.separator().props('vertical inset').classes('mx-1')
                    with ui.row().props('role="group" aria-label="확대 및 축소"').classes(
                            'items-center flex-nowrap gap-1 shrink-0'):
                        self.ratio = ui.input(value='화면 맞춤').props(
                            'dense outlined hide-bottom-space aria-label="배율" input-class="text-center tabular-nums"').classes('w-36')
                        self.ratio.on('keydown.enter', self.apply_zoom_input)
                        self.ratio.tooltip('25~300% 입력 후 Enter로 적용 · Ctrl + 마우스 휠로 확대·축소')
                        with self.ratio.add_slot('append'):
                            self.zoom_menu_button = ui.button(icon='arrow_drop_down').props(
                                'flat round dense aria-label="배율 옵션" aria-haspopup="menu"')
                            with self.zoom_menu_button:
                                with ui.menu().props('anchor="bottom right" self="top right"').classes('min-w-36') as self.zoom_menu:
                                    for zoom in (50, 100, 150, 200):
                                        ui.menu_item(f'{zoom}%', on_click=lambda zoom=zoom: self.change_zoom(zoom)).props('dense')
                                    ui.separator()
                                    ui.menu_item('확대', on_click=lambda: self.change_zoom(self.zoom + 25)).props('dense')
                                    ui.menu_item('축소', on_click=lambda: self.change_zoom(self.zoom - 25)).props('dense')
                                    ui.separator()
                                    ui.menu_item('화면 맞춤', on_click=self.fit_screen).props('dense')
                        self.minus = ui.button(icon='remove', on_click=lambda: self.change_zoom(self.zoom - 25)).props('flat round dense aria-label="축소"').tooltip('축소')
                        self.plus = ui.button(icon='add', on_click=lambda: self.change_zoom(self.zoom + 25)).props('flat round dense aria-label="확대"').tooltip('확대')
                    ui.separator().props('vertical inset').classes('mx-1')
                    with ui.row().classes('items-center flex-nowrap gap-1 shrink-0').props('role="group" aria-label="문서 조작 모드"'):
                        self.hand_button = ui.button(icon='pan_tool', on_click=lambda: self.set_mode(True)).props(
                            'flat round dense aria-label="손 도구" aria-pressed="true"').classes('bg-blue-100').tooltip('손 도구: 잡아 끌어 스크롤')
                        self.cursor_button = ui.button(icon='ads_click', on_click=lambda: self.set_mode(False)).props(
                            'flat round dense aria-label="텍스트 선택 도구" aria-pressed="false"').tooltip('커서 도구: PDF 텍스트 선택')
                    ui.space()
                    self.spinner = ui.spinner(size='sm').classes('shrink-0').props('aria-label="미리보기 로딩 중"')
                with ui.element('div').classes(
                        'w-full flex-1 min-h-0 overflow-auto bg-slate-100 rounded-b border border-t-0 border-slate-200').style(
                            'position:relative; container-type:size; cursor:grab; overscroll-behavior:contain').props(
                                'aria-label="문서 스크롤 영역" tabindex="0" data-mode="hand"') as self.viewport:
                    self.message = ui.label().classes('text-red-700 p-3 empty:hidden').props('role=alert')
                    self.page_stack = ui.element('div').style(
                        'display:flex; flex-direction:column; gap:24px; padding:24px; '
                        'width:max-content; min-width:100%; min-height:100%; justify-content:safe center; '
                        'box-sizing:border-box; pointer-events:none')
        ui.add_css(f'''
            #c{self.viewport.id} .preview-text-layer {{ position:absolute; inset:0; pointer-events:none; user-select:none; }}
            #c{self.viewport.id}[data-mode="select"] .preview-text-layer {{ pointer-events:auto; user-select:text; cursor:text; }}
            #c{self.viewport.id} .preview-text-layer svg {{ display:block; width:100%; height:100%; }}
            #c{self.viewport.id} .preview-text-layer text {{ fill:transparent; white-space:pre; }}
            #c{self.viewport.id}[data-mode="select"] .preview-text-layer text {{ user-select:text; }}
            #c{self.viewport.id} .preview-text-layer text::selection {{ background:rgb(59 130 246 / 35%); }}
        ''')
        self.viewer_card.on('wheel', self.wheel_zoom, throttle=0.15, js_handler='''event => {
            if (!event.ctrlKey) return;
            event.preventDefault();
            event.stopPropagation();
            if (event.deltaY !== 0) emit(event.deltaY < 0 ? 1 : -1);
        }''')
        self.viewport.on('dragstart', js_handler='event => event.preventDefault()')
        self.viewport.on('pointerdown', js_handler='''event => {
            if (event.button !== 0 || event.pointerType === 'touch') return;
            const el = event.currentTarget;
            if (el.dataset.mode !== 'hand') return;
            const rect = el.getBoundingClientRect();
            if (event.clientX - rect.left >= el.clientWidth ||
                event.clientY - rect.top >= el.clientHeight) return;
            el.previewPan = {x: event.clientX, y: event.clientY,
                             left: el.scrollLeft, top: el.scrollTop};
            el.setPointerCapture(event.pointerId);
            el.style.cursor = 'grabbing';
            event.preventDefault();
        }''')
        self.viewport.on('pointermove', js_handler='''event => {
            const el = event.currentTarget, pan = el.previewPan;
            if (!pan) return;
            el.scrollLeft = pan.left + pan.x - event.clientX;
            el.scrollTop = pan.top + pan.y - event.clientY;
        }''')
        for event in ('pointerup', 'pointercancel', 'lostpointercapture'):
            self.viewport.on(event, js_handler='''event => {
                const el = event.currentTarget;
                delete el.previewPan;
                el.style.cursor = el.dataset.mode === 'hand' ? 'grab' : 'default';
                if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
            }''')
        self.viewport.on('scroll', self.scrolled, throttle=0.1, js_handler='''event => {
            const el = event.currentTarget;
            const images = [...el.querySelectorAll('img[data-page]')];
            if (!images.length) return;
            const top = el.getBoundingClientRect().top + 24;
            let nearest = images[0], distance = Infinity;
            for (const image of images) {
                const d = Math.abs(image.getBoundingClientRect().top - top);
                if (d < distance) { nearest = image; distance = d; }
            }
            if (el.scrollTop > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - 2)
                nearest = images[images.length - 1];
            emit(Number(nearest.dataset.page));
        }''')
        is_pdf = Path(self.filename).suffix.lower() == '.pdf'
        for control in (self.page_tools, self.toolbar_separator):
            control.set_visibility(is_pdf)
        self.cursor_button.set_enabled(self.is_pdf)
        self.lock_watch = ui.timer(0.5, self.alive)
        self.dialog.open()

    def alive(self):
        if not self.closed and self.repository.database.is_locked:
            self.close()
        return not self.closed

    def controls(self):
        for control in (self.previous, self.number, self.next, self.ratio, self.zoom_menu_button, self.minus, self.plus, self.hand_button):
            control.set_enabled(not self.busy and bool(self.content))
        self.previous.set_enabled(not self.busy and self.page > 1)
        self.next.set_enabled(not self.busy and self.page < self.pages)
        self.minus.set_enabled(not self.busy and bool(self.content) and self.zoom > 25)
        self.plus.set_enabled(not self.busy and bool(self.content) and self.zoom < 300)
        self.spinner.set_visibility(self.busy)
        self.cursor_button.set_enabled(self.is_pdf and not self.busy and bool(self.images))

    def set_mode(self, hand):
        if self.busy or not self.alive() or (not hand and not self.is_pdf):
            return
        self.hand_mode = hand
        self.viewport.props(f'data-mode="{"hand" if hand else "select"}"')
        self.viewport.style(f'cursor:{"grab" if hand else "default"}')
        for button, selected in ((self.hand_button, hand), (self.cursor_button, not hand)):
            button.props(f'aria-pressed="{str(selected).lower()}"')
            button.classes(add='bg-blue-100' if selected else '', remove='' if selected else 'bg-blue-100')
        if hand:
            ui.run_javascript('window.getSelection()?.removeAllRanges()')

    async def load(self):
        self.busy = True
        self.content = b''
        self.clear_pages()
        self.controls()
        try:
            async with self.lock:
                if not self.alive():
                    return
                filename, content = await run.io_bound(self.repository.download, self.entry.id)
            if not self.alive():
                return
            self.filename, self.content = filename, content
            await self.render()
        except (DatabaseError, ValueError, OSError) as error:
            if self.alive():
                self.message.set_text(str(error))
        finally:
            if self.alive():
                self.busy = False
                self.controls()

    async def render(self):
        if not self.alive():
            return
        self.busy = True
        self.controls()
        self.message.set_text('')
        try:
            results = await run.io_bound(render_document, self.filename, self.content, self.zoom, self.cancelled)
            if not self.alive():
                return
            reuse_pages = len(self.images) == len(results)
            if not reuse_pages:
                self.clear_pages()
            self.pages = len(results)
            self.total.set_text(f'/ {self.pages}')
            self.number.max = self.pages
            self.number.value = self.page
            with self.page_stack:
                for index, result in enumerate(results, 1):
                    width = (f'min({result.width}px, calc(100cqw - 48px), '
                             f'calc((100cqh - 48px) * {result.width / result.height}))'
                             if self.fit else f'{result.width * self.zoom / 100}px')
                    if reuse_pages:
                        # Keep the wheel target and text selection layer alive while zooming.
                        image = self.images[index - 1]
                        image.parent_slot.parent.style(f'width:{width}')
                        image._props['src'] = result.source
                        image.update()
                        continue
                    with ui.element('div').props(f'data-document-page="{index}"').style(
                            f'position:relative; flex:none; margin:0 auto; width:{width}; '
                            f'aspect-ratio:{result.width}/{result.height}; '
                            'box-shadow:0 3px 12px rgb(15 23 42 / 18%), 0 1px 3px rgb(15 23 42 / 12%)'):
                        image = ui.element('img').props(f'alt="첨부파일 미리보기 {index}페이지" draggable="false" data-page="{index}"').style(
                            'display:block; width:100%; height:100%; user-select:none')
                        image._props['src'] = result.source
                        self.images.append(image)
                        if result.text:
                            spans = []
                            for glyph in result.text:
                                length = f'textLength="{glyph.width * 1000}" lengthAdjust="spacingAndGlyphs"' if glyph.width else ''
                                spans.append(f'<tspan x="{glyph.x * 1000}" y="{(glyph.y + glyph.height) * 1000}" '
                                             f'font-size="{glyph.height * 1000}" {length}>{escape(glyph.text)}</tspan>')
                            ui.html('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" '
                                    'preserveAspectRatio="none" xml:space="preserve"><text>' + ''.join(spans) + '</text></svg>',
                                    sanitize=False).classes('preview-text-layer')
            if self.is_pdf and not any(result.text for result in results):
                self.message.set_text('이 PDF에는 선택 가능한 텍스트가 없습니다. 스캔 문서는 이미지로 열람할 수 있습니다.')
            self.ratio.set_value('화면 맞춤' if self.fit else f'{self.zoom}%')
            self.scroll_to_page(center=True)
        except (ValueError, OSError) as error:
            if self.alive():
                self.message.set_text(str(error))
        finally:
            if self.alive():
                self.busy = False
                self.controls()

    async def change_page(self, value):
        if self.busy or not self.alive():
            return
        if not isinstance(value, (int, float)) or not 1 <= value <= self.pages or int(value) != value:
            self.number.value = self.page
            return
        self.page = int(value)
        self.scroll_to_page()
        self.controls()

    def clear_pages(self):
        for image in self.images:
            image.props(remove='src')
        self.images.clear()
        self.page_stack.clear()

    def scroll_to_page(self, *, center=False):
        ui.run_javascript(f'''requestAnimationFrame(() => {{
            const viewport = document.getElementById('c{self.viewport.id}');
            const page = viewport?.querySelector('[data-document-page="{self.page}"]');
            if (page) viewport.scrollTop = page.offsetTop - 24;
            if (viewport && {str(center).lower()}) viewport.scrollLeft = (viewport.scrollWidth - viewport.clientWidth) / 2;
        }});''')

    def scrolled(self, event):
        if self.busy or not self.alive() or not isinstance(event.args, int):
            return
        if 1 <= event.args <= self.pages:
            self.page = event.args
            self.number.value = self.page
            self.controls()

    async def apply_zoom_input(self):
        if self.busy or not self.alive():
            return
        text = (self.ratio.value or '').strip()
        if text == '화면 맞춤':
            await self.fit_screen()
            return
        try:
            value = int(text.removesuffix('%').strip())
            if not 25 <= value <= 300:
                raise ValueError
        except ValueError:
            self.ratio.set_value('화면 맞춤' if self.fit else f'{self.zoom}%')
            ui.notify('배율은 25~300 사이의 정수로 입력해 주세요.', type='warning')
            return
        await self.change_zoom(value)

    async def wheel_zoom(self, event):
        if event.args in (-1, 1):
            await self.change_zoom(self.zoom + event.args * 25)

    async def change_zoom(self, value):
        if self.busy or not self.alive():
            return
        zoom = max(25, min(300, value))
        if not self.fit and zoom == self.zoom:
            return
        self.zoom, self.fit = zoom, False
        await self.render()

    async def fit_screen(self):
        if self.busy or not self.alive():
            return
        self.zoom, self.fit = 100, True
        await self.render()

    def close(self, *, delete_dialog=True):
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.content = b''
        self.lock_watch.cancel()
        _previews.get(self.client, set()).discard(self)
        if not self.dialog.is_deleted:
            self.clear_pages()
            if delete_dialog:
                self.dialog.close()
                self.dialog.delete()
