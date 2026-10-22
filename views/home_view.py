"""세밀한 홈 격자와 위젯 배치 편집."""

from copy import deepcopy
from uuid import uuid4

from nicegui import run, ui

from database import DatabaseError
from home_layout import arrange, DEFAULT_SIZES, row_span
from widgets import WIDGETS
from views.home_interactions import POINTER, KEYBOARD


class HomeView:
    def __init__(self, repository, teachers, on_students):
        self.repository = repository
        self.teachers = teachers
        self.on_students = on_students
        self.layout = []
        self.default_sizes = {kind: {'width': w, 'height': h} for kind, (w, h) in DEFAULT_SIZES.items()}
        self.editing = False
        self.busy = False
        self.loaded = False
        self.widget_views = []

    def build(self):
        ui.add_css('''
            .home-grid { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr));
                grid-auto-rows: var(--home-cell); gap: 8px; align-items: start;
                --home-cell: calc((100cqw - 184px) / 24); }
            .home-grid-editing { min-height: 800px;
                background-image: linear-gradient(to right, #cbd5e155 1px, transparent 1px),
                    linear-gradient(to bottom, #cbd5e155 1px, transparent 1px);
                background-size: calc(var(--home-cell) + 8px) calc(var(--home-cell) + 8px); }
            .home-widget { min-width: 0; width: 100%; position: relative; overflow: auto; }
            .home-drag-handle { cursor: grab; touch-action: none; user-select: none; }
            .home-drag-handle:active { cursor: grabbing; }
            .home-resize-handle { position: absolute; z-index: 2; touch-action: none;
                border: 0; padding: 0; border-radius: 6px; background: #e6f4f1;
                display: flex; align-items: center; justify-content: center; }
            .home-resize-x { right: 0; top: 25%; width: 12px; height: 50%; cursor: ew-resize; }
            .home-resize-y { bottom: 0; left: 25%; width: 50%; height: 12px; cursor: ns-resize; }
            .home-resize-xy { right: 0; bottom: 0; width: 28px; height: 28px; cursor: nwse-resize; }
            .home-resize-handle:hover { background: #b8e2d9; }
            .home-resize-handle:focus-visible, .home-drag-handle:focus-visible { outline: 2px solid #24756b; }
            .home-resizing { outline: 2px solid #24756b; user-select: none; z-index: 3; }
            @media (max-width: 899px) {
                .home-grid { display: flex; flex-direction: column; gap: 10px; }
                .home-grid-editing { background: none; }
                .home-widget { height: var(--home-mobile-height) !important; }
                .home-drag-handle { cursor: default; }
            }
        ''')
        with ui.column().classes('w-full mx-auto gap-6 p-4 md:p-8'):
            with ui.row().classes('w-full items-center justify-between gap-4'):
                with ui.column().classes('gap-1'):
                    ui.label('홈').classes('text-sm font-semibold text-teal-700')
                    ui.label('오늘도, 마음을 잇는 시간').classes('text-3xl font-bold text-slate-800')
                    ui.label('나에게 필요한 위젯으로 하루를 준비하세요.').classes('text-slate-500')
                self.edit_button = ui.button('위젯 편집', icon='dashboard_customize', on_click=self.toggle_edit)
                self.edit_button.disable()
            with ui.row().classes('w-full items-center gap-3'):
                self.add_button = ui.button('위젯 추가', icon='add', on_click=self.open_picker).props('outline')
                self.add_button.disable()
                self.add_button.set_visibility(False)
                self.status = ui.label('위젯을 불러오는 중입니다…').classes('text-sm text-slate-500')
            with ui.element('div').classes('w-full').style('container-type: inline-size'):
                self.grid = ui.element('div').classes('home-grid w-full')
            ui.timer(0, self.load, once=True)

    async def load(self):
        try:
            self.layout = arrange(await run.io_bound(self.repository.layout))
            self.default_sizes = await run.io_bound(self.repository.widget_sizes)
            self.loaded = True
            self.edit_button.enable()
            self.add_button.enable()
            self.render()
        except (DatabaseError, ValueError) as error:
            self.status.text = str(error)
            with self.grid:
                ui.button('다시 불러오기', on_click=self.load)

    def toggle_edit(self):
        if not self.busy:
            self.editing = not self.editing
            self.render()

    def bind_geometry(self, element, instance_id):
        element.on('pointerdown', lambda e: self.change_geometry(instance_id, e.args), js_handler=POINTER)
        element.on('keydown', lambda e: self.change_geometry(instance_id, e.args), js_handler=KEYBOARD)

    def render(self):
        self.grid.clear()
        self.widget_views = []
        self.grid.classes(add='home-grid-editing' if self.editing else '',
                          remove='' if self.editing else 'home-grid-editing')
        self.edit_button.text = '편집 완료' if self.editing else '위젯 편집'
        self.add_button.set_visibility(self.editing)
        self.add_button.set_enabled(self.editing and not self.busy)
        self.status.text = ('제목을 끌어 빈 곳으로 이동 · 가장자리로 크기 조절 · 방향키로 미세 조절 · 자동 저장'
                            if self.editing else '배치는 자동 저장됩니다.')
        with self.grid:
            if not self.layout:
                with ui.column().classes('items-center w-full p-10 text-slate-500').style('grid-column: 1 / -1; grid-row: span 5'):
                    ui.icon('widgets', size='40px')
                    ui.label('아직 배치된 위젯이 없습니다.')
                    if self.editing:
                        ui.button('첫 위젯 추가', icon='add', on_click=self.open_picker).props('flat')
                    else:
                        ui.label('위젯 편집을 눌러 위젯을 추가하세요.')
            for index, item in enumerate(self.layout):
                widget = WIDGETS[item['kind']]
                with ui.card().classes('home-widget rounded-2xl shadow-sm p-4 gap-3').style(
                        f'grid-column: {item["x"] + 1} / span {item["width"]}; '
                        f'grid-row: {item["y"] + 1} / span {row_span(item)}; '
                        f'height: calc({row_span(item)} * var(--home-cell) + {(row_span(item) - 1) * 8}px); '
                        f'--home-mobile-height: {item["height"]}px').props(
                        f'data-kind={item["kind"]} data-instance={item["id"]} data-width={item["width"]} '
                        f'data-height={item["height"]} data-x={item["x"]} data-y={item["y"]}'):
                    with ui.row().classes('w-full items-center flex-nowrap gap-2' + (' home-drag-handle' if self.editing else '')) as header:
                        if self.editing:
                            ui.icon('drag_indicator').classes('shrink-0 text-slate-400')
                        ui.icon(widget.icon, size='24px').classes('shrink-0 text-teal-700')
                        ui.label(widget.title).classes('min-w-0 break-words font-bold text-slate-800')
                    if self.editing:
                        header.props(f'tabindex=0 role=button aria-label="{widget.title} 위치 이동"')
                        self.bind_geometry(header, item['id'])
                        with ui.row().classes('w-full gap-2'):
                            ui.button(icon='delete_outline', on_click=lambda index=index: self.remove(index)).props(
                                f'flat round color=negative aria-label="{widget.title} 위젯 삭제"').tooltip('위젯 삭제 (데이터는 보존)')
                        if hasattr(widget, 'build_settings'):
                            view = widget(self.repository, self.teachers, item['id'], self.refresh_todos)
                            view.build_settings()
                        for axis, label, icon in (('x', '너비 조절', 'drag_indicator'),
                                                  ('y', '높이 조절', 'drag_handle'),
                                                  ('xy', '크기 조절', 'open_in_full')):
                            with ui.element('button').classes(f'home-resize-handle home-resize-{axis} text-teal-700').props(
                                    f'type=button data-resize-axis={axis} aria-label="{widget.title} {label}"') as handle:
                                ui.icon(icon, size='16px').classes('pointer-events-none')
                            self.bind_geometry(handle, item['id'])
                    else:
                        view = widget(self.repository, self.teachers, item['id'], self.refresh_todos)
                        self.widget_views.append(view)
                        view.build()

    async def refresh_todos(self, source):
        for view in list(self.widget_views):
            if view is not source and view.kind == 'todo' and not view.busy and not view.body.is_deleted:
                await view.reload()

    def open_picker(self):
        if self.busy or not self.loaded or not self.editing:
            return
        with ui.dialog() as dialog, ui.card().classes('w-[480px] max-w-full p-6'):
            ui.label('위젯 추가').classes('text-xl font-bold')
            kind = ui.select({key: widget.title for key, widget in WIDGETS.items()},
                             value='clock', label='위젯').classes('w-full')
            ui.label('추가한 뒤 제목을 끌어 이동하고 가장자리로 크기를 조절하세요.').classes('text-sm text-slate-500')

            async def add():
                if self.busy or not self.editing:
                    return
                w = self.default_sizes[kind.value]['width']
                h = self.default_sizes[kind.value]['height']
                if await self.commit(arrange([*self.layout, {'id': uuid4().hex, 'kind': kind.value,
                                                            'width': int(w), 'height': int(h)}])):
                    dialog.close()
            with ui.row().classes('self-end'):
                ui.button('닫기', on_click=dialog.close).props('flat')
                ui.button('추가', icon='add', on_click=add)
        dialog.open()

    async def change_geometry(self, instance_id, size):
        if not self.editing or self.busy or not isinstance(size, dict):
            return
        layout = deepcopy(self.layout)
        for item in layout:
            if item['id'] != instance_id:
                continue
            changes = {key: value for key, value in size.items() if key in ('x', 'y', 'width', 'height')}
            candidate = {**item, **changes}
            if (any(type(value) is not int for value in changes.values())
                    or not 1 <= candidate['width'] <= 24 or not 160 <= candidate['height'] <= 1600
                    or not 0 <= candidate['x'] <= 23 or candidate['y'] < 0):
                self.render()
                return
            item.update(changes)
            item['x'] = min(item['x'], 24 - item['width'])
            await self.commit(arrange(layout, priority=instance_id))
            return

    async def remove(self, index):
        if not self.editing or self.busy:
            return
        await self.commit([item for i, item in enumerate(self.layout) if i != index])

    async def commit(self, layout):
        if self.busy:
            return False
        self.busy = True
        self.edit_button.disable()
        self.add_button.disable()
        self.grid.classes(add='pointer-events-none opacity-60')
        success = False
        try:
            await run.io_bound(self.repository.save_layout, layout)
            self.layout = layout
            success = True
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
        finally:
            self.busy = False
            self.edit_button.enable()
            self.add_button.enable()
            self.grid.classes(remove='pointer-events-none opacity-60')
            self.render()
        return success
