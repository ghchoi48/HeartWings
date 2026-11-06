"""세밀한 홈 격자와 위젯 배치 편집."""

from copy import deepcopy
from functools import partial
from random import choice
from uuid import uuid4

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.views.home.home_layout import arrange, DEFAULT_SIZES, row_span, COLUMNS, GRID_VERSION
from maeumnarae.widgets import WIDGETS
from maeumnarae.views.home.home_interactions import POINTER, KEYBOARD


WELCOME_MESSAGES = (
    '오늘도 만나서 반가워요.',
    '마음을 잇는 하루를 함께 시작해요.',
    '오늘도 따뜻한 만남이 기다리고 있어요.',
    '선생님의 하루를 응원해요.',
    '잠시 숨을 고르고 하루를 시작해 볼까요?',
    '오늘도 선생님의 따뜻한 마음을 응원해요.',
    '작은 미소로 하루를 열어 보세요.',
    '선생님 자신을 돌보는 시간도 챙겨 주세요.',
    '오늘도 함께할 수 있어 기뻐요.',
    '편안한 마음으로 오늘을 준비해요.',
)


class HomeView:
    def __init__(self, repository, teachers, on_students, school=None, *, on_calendar=None, on_open_schedule=None, on_open_linked=None, is_active=None):
        self.repository = repository
        self.teachers = teachers
        self.on_students = on_students
        self.calendar_callbacks = dict(on_calendar=on_calendar, on_open=on_open_schedule, on_open_linked=on_open_linked,
                                       is_active=is_active)
        self.school = school
        self.welcome_message = choice(WELCOME_MESSAGES)
        self.layout = []
        self.default_sizes = {kind: {'width': w, 'height': h} for kind, (w, h) in DEFAULT_SIZES.items()}
        self.editing = False
        self.busy = False
        self.loaded = False
        self.widget_views = []

    def build(self):
        ui.add_css('''
            .home-grid { display: grid; grid-template-columns: repeat(48, minmax(0, 1fr));
                grid-auto-rows: var(--home-cell); gap: 8px; align-items: start;
                --home-cell: calc((100cqw - 376px) / 48); }
            .home-grid-editing { min-height: 800px;
                background-image: linear-gradient(to right, #cbd5e155 1px, transparent 1px),
                    linear-gradient(to bottom, #cbd5e155 1px, transparent 1px);
                background-size: calc(var(--home-cell) + 8px) calc(var(--home-cell) + 8px); }
            .home-widget { min-width: 0; width: 100%; position: relative; overflow: hidden;
                flex-wrap: nowrap; }
            .home-widget-header { height: 36px; min-height: 36px; flex: 0 0 36px; }
            .home-widget-content { flex: 1 1 0%; min-width: 0; min-height: 0;
                overflow: auto; flex-wrap: nowrap; }
            .home-widget-content > :not(.memo-editor) { flex-shrink: 0; }
            .home-widget[data-kind="scheduled_journals"],
            .home-widget[data-kind="scheduled_journals"] > .home-widget-content { gap: 4px; }
            .home-drag-handle { cursor: grab; touch-action: none; user-select: none; }
            .home-drag-handle:active { cursor: grabbing; }
            .home-resize-handle { position: absolute; z-index: 2; touch-action: none;
                border: 0; padding: 0; border-radius: 6px; background: #e6f4f1;
                display: flex; align-items: center; justify-content: center; }
            .home-resize-x { right: 0; top: 25%; width: 12px; height: 50%; cursor: ew-resize; }
            .home-resize-y { bottom: 0; left: 25%; width: 50%; height: 12px; cursor: ns-resize; }
            .home-resize-xy { right: 0; bottom: 0; width: 28px; height: 28px; cursor: nwse-resize; }
            .home-resize-handle:hover { background: #b8e2d9; }
            .home-resize-handle:focus-visible, .home-drag-handle:focus-visible { outline: 2px solid var(--q-primary); }
            .home-resizing { outline: 2px solid var(--q-primary); user-select: none; z-index: 3; }
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
                    ui.label('홈').classes('text-sm font-semibold text-primary')
                    ui.label('오늘도, 마음을 잇는 시간').classes('text-3xl font-bold text-slate-800')
                    self.greeting = ui.label(f'선생님, {self.welcome_message}').classes('text-slate-500')
                self.edit_button = ui.button('위젯 편집', icon='dashboard_customize', on_click=self.toggle_edit)
                self.edit_button.disable()
            with ui.row().classes('w-full items-center gap-3') as self.controls:
                self.add_button = ui.button('위젯 추가', icon='add', on_click=self.open_picker).props('outline')
                self.add_button.disable()
                self.add_button.set_visibility(False)
                self.status = ui.label('위젯을 불러오는 중입니다…').classes('text-sm text-slate-500')
            with ui.element('div').classes('w-full').style('container-type: inline-size'):
                self.grid = ui.element('div').classes('home-grid w-full')
            ui.timer(0, self.load, once=True)

    async def load(self):
        try:
            if self.school is not None:
                settings = await run.io_bound(self.school.get)
                name = settings.counselor_name.strip()
                self.greeting.text = f'{name + " " if name else ""}선생님, {self.welcome_message}'
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
        self.controls.set_visibility(self.editing)
        self.status.text = ('제목을 끌어 빈 곳으로 이동 · 가장자리로 크기 조절 · 방향키로 미세 조절 · 자동 저장'
                            if self.editing else '')
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
                view = widget(self.repository, self.teachers, item['id'], self.refresh_todos,
                              **(self.calendar_callbacks if item['kind'] == 'calendar' else {}))
                self.widget_views.append(view)
                with ui.card().classes('home-widget rounded-2xl shadow-sm p-4 gap-3').style(
                        f'grid-column: {item["x"] + 1} / span {item["width"]}; '
                        f'grid-row: {item["y"] + 1} / span {row_span(item)}; '
                        f'height: calc({row_span(item)} * var(--home-cell) + {(row_span(item) - 1) * 8}px); '
                        f'--home-mobile-height: {item["height"]}px').props(
                        f'data-kind={item["kind"]} data-instance={item["id"]} data-width={item["width"]} '
                        f'data-height={item["height"]} data-x={item["x"]} data-y={item["y"]}'):
                    with ui.row().classes('home-widget-header w-full items-center flex-nowrap gap-2' + (' home-drag-handle' if self.editing else '')) as header:
                        if self.editing:
                            ui.icon('drag_indicator').classes('shrink-0 text-slate-400')
                        ui.icon(widget.icon, size='24px').classes('shrink-0 text-primary')
                        ui.label(widget.title).classes('min-w-0 truncate font-bold text-slate-800').tooltip(widget.title)
                        if self.editing or hasattr(view, 'build_header_actions'):
                            ui.space()
                        if hasattr(view, 'build_header_actions'):
                            view.build_header_actions()
                        if self.editing:
                            ui.button(icon='delete_outline', on_click=lambda index=index: self.remove(index)).props(
                                f'flat round dense color=negative aria-label="{widget.title} 위젯 삭제"').classes('shrink-0').tooltip('위젯 삭제 (데이터는 보존)')
                            if hasattr(view, 'open_settings'):
                                ui.button(icon='edit', on_click=view.open_settings).props(
                                    f'flat round dense aria-label="{widget.title} 설정 수정"').classes('shrink-0').tooltip('설정 수정')
                    if self.editing:
                        header.props(f'tabindex=0 role=button aria-label="{widget.title} 위치 이동"')
                        self.bind_geometry(header, item['id'])
                        for axis, label, icon in (('x', '너비 조절', 'drag_indicator'),
                                                  ('y', '높이 조절', 'drag_handle'),
                                                  ('xy', '크기 조절', 'open_in_full')):
                            with ui.element('button').classes(f'home-resize-handle home-resize-{axis} text-primary').props(
                                    f'type=button data-resize-axis={axis} aria-label="{widget.title} {label}"') as handle:
                                ui.icon(icon, size='16px').classes('pointer-events-none')
                            self.bind_geometry(handle, item['id'])
                    with ui.column().classes('home-widget-content w-full gap-3'):
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
            ui.label('추가한 뒤 제목을 끌어 이동하고 가장자리로 크기를 조절하세요.').classes('text-sm text-slate-500')

            async def add(kind):
                if self.busy or not self.editing:
                    return
                w = self.default_sizes[kind]['width']
                h = self.default_sizes[kind]['height']
                if await self.commit(arrange([*self.layout, {'id': uuid4().hex, 'kind': kind,
                                                            'width': int(w), 'height': int(h), 'grid': GRID_VERSION}])):
                    dialog.close()
            with ui.column().classes('w-full gap-2'):
                for kind, widget in WIDGETS.items():
                    ui.button(widget.title, icon=widget.icon, on_click=partial(add, kind)).props(
                        'outline align=left').classes('w-full')
            with ui.row().classes('self-end'):
                ui.button('닫기', on_click=dialog.close).props('flat')
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
                    or not 1 <= candidate['width'] <= COLUMNS or not 160 <= candidate['height'] <= 1600
                    or not 0 <= candidate['x'] < COLUMNS or candidate['y'] < 0):
                self.render()
                return
            item.update(changes)
            item['x'] = min(item['x'], COLUMNS - item['width'])
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
