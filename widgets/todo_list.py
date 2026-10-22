"""목록별 할 일과 완료 내역, 기한·우선순위를 관리한다."""

from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from database import DatabaseError

PRIORITIES = {'high': '높음', 'normal': '보통', 'low': '낮음'}
KST = timezone(timedelta(hours=9))


class TodoList:
    kind = 'todo'
    title = 'Todo list'
    icon = 'checklist'

    def __init__(self, home, teachers, instance_id=None, on_change=None):
        self.repository = home
        self.instance_id = instance_id
        self.on_change = on_change
        self.busy = False
        self.loading = False
        self.selected = None

    def build(self) -> None:
        with ui.column().classes('w-full gap-3 flex-nowrap') as self.body:
            with ui.row().classes('w-full items-center flex-nowrap'):
                self.selector = ui.select({}, label='할 일 목록', on_change=self.select).props('outlined dense').classes('flex-1 min-w-0')
                ui.button(icon='playlist_add', on_click=self.new_list).props('flat round aria-label="목록 만들기"')
            with ui.row().classes('w-full items-center flex-nowrap gap-2 overflow-x-auto'):
                self.input = ui.input('새 할 일').props('outlined dense maxlength=300').classes('flex-1 min-w-32')
                self.input.on('keydown.enter', self.add)
                self.due = ui.input('기한', value='').props('type=date outlined dense clearable').classes('w-40 shrink-0')
                self.priority = ui.select(PRIORITIES, value='normal', label='우선순위').props('outlined dense').classes('w-24 shrink-0')
                ui.button(icon='add', on_click=self.add).props('round flat aria-label="할 일 추가"').classes('shrink-0')
            self.summary = ui.label().classes('text-xs text-slate-500')
            self.items = ui.column().classes('w-full gap-1')
            with ui.expansion('완료한 할 일 (0)', icon='task_alt').props('dense').classes('w-full') as self.completed:
                self.history = ui.column().classes('w-full gap-1')
        ui.timer(0, self.reload, once=True)

    async def reload(self):
        try:
            state = await run.io_bound(self.repository.todo_state, self.instance_id)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            return
        if self.body.is_deleted:
            return
        self.loading = True
        try:
            self.selected = state['selected_todo_list']
            self.selector.set_options({entry['id']: entry['name'] for entry in state['todo_lists']}, value=self.selected)
        finally:
            self.loading = False
        items = [item for item in state['todos'] if item.get('list_id', 1) == self.selected]
        pending = sorted((item for item in items if not item['done']), key=lambda item: (
            {'high': 0, 'normal': 1, 'low': 2}[item.get('priority', 'normal')], item.get('due_date') or '9999', -item['id']))
        done = sorted((item for item in items if item['done']),
                      key=lambda item: (item.get('completed_at', ''), item['id']), reverse=True)
        self.summary.text = f'남은 할 일 {len(pending)}개 · 완료 {len(done)}개'
        self.items.clear()
        self.history.clear()
        with self.items:
            if not pending:
                ui.label('남은 할 일이 없습니다.').classes('text-sm text-slate-400 py-2')
            for item in pending:
                self.row(item)
        self.completed.text = f'완료한 할 일 ({len(done)})'
        with self.history:
            if not done:
                ui.label('완료한 할 일이 없습니다.').classes('text-sm text-slate-400')
            for item in done:
                self.row(item)

    def row(self, item):
        with ui.column().classes('w-full gap-0 border-b border-slate-100 pb-2'):
            with ui.row().classes('w-full items-center flex-nowrap gap-1'):
                ui.checkbox(item['title'], value=bool(item['done']), on_change=lambda e: self.change(
                    self.repository.complete_todo, item['id'], e.value)).classes(
                        'flex-1 min-w-0 break-words' + (' line-through text-slate-400' if item['done'] else ''))
                ui.button(icon='edit', on_click=lambda: self.edit(item)).props('flat round size=sm aria-label="할 일 수정"')
                ui.button(icon='close', on_click=lambda: self.change(self.repository.delete_todo, item['id'])).props(
                    'flat round size=sm aria-label="할 일 삭제"')
            due = item.get('due_date', '')
            overdue = due and not item['done'] and due < datetime.now(KST).date().isoformat()
            priority = item.get('priority', 'normal')
            with ui.row().classes('gap-2 pl-3 items-center'):
                ui.badge(PRIORITIES[priority], color={'high': 'red', 'normal': 'teal', 'low': 'grey'}[priority]).props('outline')
                ui.label(('기한 지남 · ' if overdue else '기한 ') + due if due else '기한 없음').classes(
                    'text-xs ' + ('text-red-600' if overdue else 'text-slate-500'))
                if item.get('completed_at'):
                    date = datetime.fromisoformat(item['completed_at']).astimezone(KST)
                    ui.label(f'{date:%m/%d %H:%M} 완료').classes('text-xs text-slate-400')

    async def select(self, event):
        if self.loading or event.value is None or event.value == self.selected:
            return
        await self.change(self.repository.select_todo_list, event.value, self.instance_id)

    def new_list(self):
        with ui.dialog() as dialog, ui.card().classes('w-80 max-w-full'):
            ui.label('새 할 일 목록').classes('text-lg font-bold')
            name = ui.input('목록 이름').props('outlined maxlength=60').classes('w-full')
            async def save():
                if await self.change(self.repository.add_todo_list, name.value or '', self.instance_id):
                    dialog.close()
            name.on('keydown.enter', save)
            with ui.row():
                ui.button('취소', on_click=dialog.close).props('flat')
                ui.button('만들기', on_click=save)
        dialog.open()

    def edit(self, item):
        with ui.dialog() as dialog, ui.card().classes('w-96 max-w-full'):
            ui.label('할 일 수정').classes('text-lg font-bold')
            title = ui.input('할 일', value=item['title']).props('outlined maxlength=300').classes('w-full')
            due = ui.input('기한', value=item.get('due_date', '')).props('type=date outlined clearable').classes('w-full')
            priority = ui.select(PRIORITIES, value=item.get('priority', 'normal'), label='우선순위').props('outlined').classes('w-full')
            async def save():
                if await self.change(self.repository.edit_todo, item['id'], title.value or '', due.value or '', priority.value):
                    dialog.close()
            with ui.row():
                ui.button('취소', on_click=dialog.close).props('flat')
                ui.button('저장', on_click=save)
        dialog.open()

    async def add(self):
        if self.selected is not None:
            await self.change(self.repository.add_todo, self.input.value or '', self.selected,
                              self.due.value or '', self.priority.value, clear=True)

    async def change(self, action, *args, clear=False):
        if self.busy:
            return False
        self.busy = True
        self.body.classes(add='pointer-events-none opacity-60')
        try:
            await run.io_bound(action, *args)
            if clear:
                self.input.value = ''
                self.due.value = ''
                self.priority.value = 'normal'
            await self.reload()
            if self.on_change is not None:
                await self.on_change(self)
            return True
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
            await self.reload()
            return False
        finally:
            self.body.classes(remove='pointer-events-none opacity-60')
            self.busy = False
