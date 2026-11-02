"""목록별 할 일과 완료 내역, 기한·우선순위를 관리한다."""

from datetime import datetime, timedelta, timezone

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError

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
        due = item.get('due_date', '')
        overdue = due and not item['done'] and due < datetime.now(KST).date().isoformat()
        priority = item.get('priority', 'normal')
        with ui.column().classes('w-full gap-0 border-b border-slate-100 pb-2'):
            with ui.row().classes('w-full items-center flex-nowrap gap-1 overflow-x-auto'):
                ui.checkbox(value=bool(item['done']), on_change=lambda e: self.change(
                    self.repository.complete_todo, item['id'], e.value)).props(
                        'aria-label="할 일 완료"').classes('shrink-0')
                title = ui.input(value=item['title']).props(
                    'dense borderless maxlength=300 aria-label="할 일 내용 수정"').classes(
                        'flex-1 min-w-32' + (' line-through text-slate-400' if item['done'] else ''))
                saving_title = False

                async def save_title():
                    nonlocal saving_title
                    value = (title.value or '').strip()
                    if saving_title or self.busy or value == item['title']:
                        return
                    if not value:
                        title.value = item['title']
                        ui.notify('할 일 내용을 입력해 주세요.', type='warning')
                        return
                    saving_title = True
                    try:
                        await self.change(self.repository.edit_todo, item['id'], value,
                                          item.get('due_date', ''), item.get('priority', 'normal'))
                    finally:
                        saving_title = False

                def cancel_title():
                    title.value = item['title']

                title.on('keydown.enter', save_title)
                title.on('blur', save_title)
                title.on('keydown.escape', cancel_title)
                with ui.chip(PRIORITIES[priority],
                             color={'high': 'red-1', 'normal': 'app-primary-soft', 'low': 'grey-2'}[priority],
                             text_color={'high': 'red-9', 'normal': 'primary', 'low': 'grey-8'}[priority]).props(
                        'dense clickable aria-label="우선순위 수정"').classes('shrink-0').tooltip('우선순위 수정'):
                    with ui.menu():
                        for value, label in PRIORITIES.items():
                            ui.menu_item(label, on_click=lambda value=value: self.update_details(
                                item, priority=value))
                with ui.button(due or '기한 없음', color='red' if overdue else 'grey').props(
                        'flat dense size=sm no-caps aria-label="기한 수정"').style('font-size: calc(12px + 1pt)').classes('shrink-0').tooltip(
                        '기한 지남 · 기한 수정' if overdue else '기한 수정'):
                    with ui.menu() as due_menu:
                        async def set_due(value):
                            due_menu.close()
                            await self.update_details(item, due_date=value or '')

                        ui.date(value=due or None, on_change=lambda e: set_due(e.value)).props('mask=YYYY-MM-DD')
                        ui.button('기한 없음', on_click=lambda: set_due('')).props('flat').classes('w-full')
                ui.button(icon='close', on_click=lambda: self.change(self.repository.delete_todo, item['id'])).props(
                    'flat round size=sm aria-label="할 일 삭제"').classes('shrink-0')
            if item.get('completed_at'):
                date = datetime.fromisoformat(item['completed_at']).astimezone(KST)
                ui.label(f'{date:%m/%d %H:%M} 완료').classes('text-xs text-slate-400 pl-3')

    async def update_details(self, item, *, due_date=None, priority=None):
        await self.change(self.repository.edit_todo, item['id'], item['title'],
                          item.get('due_date', '') if due_date is None else due_date,
                          item.get('priority', 'normal') if priority is None else priority)

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

    async def add(self):
        if self.selected is not None:
            await self.change(self.repository.add_todo, self.input.value or '', self.selected,
                              '', 'normal', clear=True)

    async def change(self, action, *args, clear=False):
        if self.busy:
            return False
        self.busy = True
        self.body.classes(add='pointer-events-none opacity-60')
        try:
            await run.io_bound(action, *args)
            if clear:
                self.input.value = ''
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
