"""반응형 홈 그리드와 위젯 배치 편집. 실제 위젯은 widgets에 둔다."""

from copy import deepcopy
from uuid import uuid4

from nicegui import run, ui

from database import DatabaseError
from widgets import WIDGETS
from views.home_interactions import RESIZE_POINTER, RESIZE_KEYBOARD


class HomeView:
    def __init__(self, repository, teachers, on_students):
        self.repository = repository
        self.teachers = teachers
        self.on_students = on_students
        self.layout = []
        self.editing = False
        self.busy = False
        self.loaded = False
        self.widget_views = []

    def build(self):
        ui.add_css('''
            .home-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1.25rem; }
            .home-widget { min-width: 0; width: 100%; align-self: start; min-height: 290px; position: relative; overflow: auto; }
            .home-drag-handle { cursor: grab; touch-action: none; user-select: none; }
            .home-drag-handle:active { cursor: grabbing; }
            .home-resize-handle { position: absolute; z-index: 2; touch-action: none;
                border: 0; padding: 0; border-radius: 6px; background: #e6f4f1;
                display: flex; align-items: center; justify-content: center; }
            .home-resize-x { right: 0; top: 25%; width: 12px; height: 50%; cursor: ew-resize; }
            .home-resize-y { bottom: 0; left: 25%; width: 50%; height: 12px; cursor: ns-resize; }
            .home-resize-xy { right: 0; bottom: 0; width: 28px; height: 28px; cursor: nwse-resize; }
            .home-resize-handle:hover { background: #b8e2d9; }
            .home-resize-handle:focus-visible { outline: 2px solid #24756b; }
            .home-resizing { outline: 2px solid #24756b; user-select: none; }
            .home-drop-placeholder { opacity: .35; outline: 2px dashed #24756b; }
            @media (min-width: 900px) {
                .home-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .home-span-2, .home-span-3 { grid-column: span 2; }
            }
            @media (min-width: 1280px) {
                .home-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
                .home-span-3 { grid-column: span 3; }
            }
        ''')
        with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
            with ui.row().classes('w-full items-center justify-between gap-4'):
                with ui.column().classes('gap-1'):
                    ui.label('홈').classes('text-sm font-semibold text-teal-700')
                    ui.label('오늘도, 마음을 잇는 시간').classes('text-3xl font-bold text-slate-800')
                    ui.label('나에게 필요한 위젯으로 하루를 준비하세요.').classes('text-slate-500')
                ui.button('학생 관리', icon='arrow_forward', on_click=self.on_students).props('flat')
            with ui.row().classes('w-full items-center gap-3'):
                self.edit_button = ui.button('배치 편집', icon='dashboard_customize', on_click=self.toggle_edit)
                self.edit_button.disable()
                self.add_button = ui.button('위젯 추가', icon='add', on_click=self.open_picker).props('outline')
                self.add_button.disable()
                self.status = ui.label('위젯을 불러오는 중입니다…').classes('text-sm text-slate-500')
            self.grid = ui.column().classes('home-grid w-full')
            self.sortable = self.grid.make_sortable(
                handle='.home-drag-handle', on_end=self.drop,
                ghost_class='home-drop-placeholder',
                options={'disabled': True, 'draggable': '.home-widget'})
            ui.timer(0, self.load, once=True)

    async def load(self):
        try:
            self.layout = await run.io_bound(self.repository.layout)
            self.loaded = True
            self.edit_button.enable()
            self.add_button.enable()
            self.render()
        except DatabaseError as error:
            self.status.text = str(error)
            with self.grid:
                ui.button('다시 불러오기', on_click=self.load)

    def toggle_edit(self):
        if self.busy:
            return
        self.editing = not self.editing
        self.render()

    def render(self):
        self.grid.clear()
        self.widget_views = []
        self.sortable.enable() if self.editing else self.sortable.disable()
        self.edit_button.text = '편집 완료' if self.editing else '배치 편집'
        self.status.text = ('제목을 끌어 배치하고 오른쪽·아래쪽 가장자리 또는 모서리로 크기를 조절하세요. 변경 즉시 저장됩니다.'
                            if self.editing else '배치는 자동 저장됩니다.')
        with self.grid:
            if not self.layout:
                with ui.column().classes('items-center w-full p-10 home-span-3 text-slate-500'):
                    ui.icon('widgets', size='40px')
                    ui.label('아직 배치된 위젯이 없습니다.')
                    ui.button('첫 위젯 추가', icon='add', on_click=self.open_picker).props('flat')
            for index, item in enumerate(self.layout):
                widget = WIDGETS[item['kind']]
                with ui.card().classes(f'home-widget home-span-{item["span"]} rounded-2xl shadow-sm p-5 gap-4').style(
                        f'height: {item.get("height", 290)}px').props(f'data-kind={item["kind"]} data-instance={item["id"]} data-span={item["span"]}'):
                    with ui.row().classes('w-full items-center gap-2' + (' home-drag-handle' if self.editing else '')):
                        if self.editing:
                            ui.icon('drag_indicator').classes('text-slate-400')
                        ui.icon(widget.icon).classes('text-teal-700')
                        ui.label(widget.title).classes('font-bold text-slate-800')
                    if self.editing:
                        with ui.row().classes('w-full items-center gap-1'):
                            for delta, icon, label in ((-1, 'arrow_back', '앞으로'), (1, 'arrow_forward', '뒤로')):
                                button = ui.button(icon=icon, on_click=lambda index=index, delta=delta: self.move(index, delta)).props(
                                    f'flat round size=sm aria-label="{widget.title} {label}"').tooltip(label)
                                button.set_enabled(0 <= index + delta < len(self.layout))
                            ui.select({1: '1열', 2: '2열', 3: '3열'}, value=item['span'], label='너비',
                                      on_change=lambda e, index=index: self.resize(index, e.value)).props('dense outlined').classes('w-24')
                            ui.space()
                            ui.button(icon='delete_outline', on_click=lambda index=index: self.remove(index)).props(
                                f'flat round color=negative aria-label="{widget.title} 위젯 삭제"').tooltip('위젯 삭제 (데이터는 보존)')
                        ui.label('오른쪽: 너비 · 아래쪽: 높이 · 모서리: 가로·세로').classes('text-sm text-slate-400 py-8')
                        for axis, label, icon in (('x', '너비 조절', 'drag_indicator'),
                                                  ('y', '높이 조절', 'drag_handle'),
                                                  ('xy', '크기 조절', 'open_in_full')):
                            with ui.element('button').classes(f'home-resize-handle home-resize-{axis} text-teal-700').props(
                                    f'type=button data-resize-axis={axis} aria-label="{widget.title} {label}"') as handle:
                                ui.icon(icon, size='16px').classes('pointer-events-none')
                            handle.on('pointerdown', lambda e, instance_id=item['id']: self.resize_drag(instance_id, e.args),
                                      js_handler=RESIZE_POINTER)
                            handle.on('keydown', lambda e, instance_id=item['id']: self.resize_drag(instance_id, e.args),
                                      js_handler=RESIZE_KEYBOARD)
                    else:
                        view = widget(self.repository, self.teachers, item['id'], self.refresh_todos)
                        self.widget_views.append(view)
                        view.build()

    async def refresh_todos(self, source):
        """같은 목록을 표시하는 다른 Todo 위젯에도 변경 사항을 반영한다."""
        for view in list(self.widget_views):
            if view is not source and view.kind == 'todo' and not view.busy and not view.body.is_deleted:
                await view.reload()

    def open_picker(self):
        if self.busy or not self.loaded:
            return
        with ui.dialog() as dialog, ui.card().classes('w-96 max-w-full p-6'):
            ui.label('위젯 추가').classes('text-xl font-bold')
            ui.label('같은 위젯도 여러 개 추가할 수 있습니다.').classes('text-sm text-slate-500')
            for kind, widget in WIDGETS.items():

                async def add(kind=kind):
                    dialog.close()
                    await self.commit([*self.layout, {'id': uuid4().hex, 'kind': kind, 'span': 1,
                                                    'height': getattr(WIDGETS[kind], 'default_height', 290)}])

                ui.button(widget.title, icon=widget.icon,
                                   on_click=add).props('flat align=left').classes('w-full')
            ui.button('닫기', on_click=dialog.close).props('flat').classes('self-end')
        dialog.open()

    async def drop(self, event):
        if not self.editing or self.busy:
            return
        layout = deepcopy(self.layout)
        if (0 <= event.old_index < len(layout) and 0 <= event.new_index < len(layout)
                and event.old_index != event.new_index):
            layout.insert(event.new_index, layout.pop(event.old_index))
            await self.commit(layout)

    async def resize_drag(self, instance_id, size):
        if not self.editing or self.busy or not isinstance(size, dict):
            return
        span, height = size.get('span'), size.get('height')
        if type(span) is not int or span not in (1, 2, 3) or type(height) is not int or not 290 <= height <= 900:
            return
        layout = deepcopy(self.layout)
        for item in layout:
            if item['id'] == instance_id:
                item.update(span=span, height=height)
                await self.commit(layout)
                return

    async def move(self, index, delta):
        layout = deepcopy(self.layout)
        target = index + delta
        if 0 <= target < len(layout):
            layout[index], layout[target] = layout[target], layout[index]
            await self.commit(layout)

    async def resize(self, index, span):
        layout = deepcopy(self.layout)
        layout[index]['span'] = span
        await self.commit(layout)

    async def remove(self, index):
        await self.commit([item for i, item in enumerate(self.layout) if i != index])

    async def commit(self, layout):
        if self.busy:
            return
        self.busy = True
        self.sortable.disable()
        self.edit_button.disable()
        self.add_button.disable()
        self.grid.classes(add='pointer-events-none opacity-60')
        try:
            await run.io_bound(self.repository.save_layout, layout)
            self.layout = layout
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
        finally:
            self.busy = False
            self.edit_button.enable()
            self.add_button.enable()
            self.grid.classes(remove='pointer-events-none opacity-60')
            self.render()
