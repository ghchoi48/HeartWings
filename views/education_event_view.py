"""교육/행사 목록과 선택 항목의 상세 내용을 나란히 표시한다."""
from datetime import datetime

from nicegui import run, ui

from views.attachment_view import attachment_button

from views.delete_action import delete_button

from views.time_inputs import storage_time, time_input

from database import DatabaseError
from models import EducationEvent, EducationEventInput
from repositories.education_event_repo import EducationEventRepository
from views.counseling_view import KST
from views.counseling_content import clean_html, editor_html


class EducationEventView:
    def __init__(self, repository: EducationEventRepository):
        self.repository = repository
        self.selected: EducationEvent | None = None
        self.selection_request = 0
        self.list_request = 0
        self.editor_saving = False
        self.editor_fields = {}
        self.editor_original = {}

    @property
    def editor_open(self):
        return self.editor_saving or self.editor_original != self.editor_values()

    def editor_values(self):
        return {key: field.value for key, field in self.editor_fields.items()}

    async def confirm_editor_discard(self):
        if self.editor_saving:
            return False
        if not self.editor_open:
            return True
        with ui.context.client.content:
            with ui.dialog().props('persistent') as confirm, ui.card():
                ui.label('저장하지 않은 내용을 버릴까요?')
                ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
        try:
            return bool(await confirm)
        finally:
            confirm.delete()

    def clear_editor(self):
        self.editor_fields = {}
        self.editor_original = {}
        self.details.clear()

    def build(self):
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('교육/행사').classes('text-3xl font-bold text-slate-800')
            ui.label('목록에서 교육/행사를 선택하여 바로 작성하거나 수정하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[2fr_3fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('교육/행사 목록').classes('text-xl font-bold')
                        with ui.row().classes('items-center gap-2'):
                            delete_button(self.repository.database, 'education', lambda: self.selected,
                                          self.after_deleted, blocked=lambda: self.editor_open, icon_only=True).bind_visibility_from(
                                              self, 'selected', backward=lambda value: value is not None)
                            ui.button('새 교육/행사', icon='add', on_click=lambda: self.open_editor())
                    self.table = ui.table(columns=[
                        dict(name=k, label=v, field=k, align='left', sortable=True)
                        for k, v in [('category', '구분'), ('title', '교육/행사명'), ('event_date', '날짜')]
                    ], rows=[], row_key='id', pagination=10, selection='single',
                        on_select=self.row_selected).classes('w-full').props(
                        'flat no-data-label="등록된 교육/행사가 없습니다" no-results-label="검색 결과가 없습니다"')
                    with self.table.add_slot('top'):
                        ui.input('교육/행사 검색').props('outlined dense clearable debounce=300').classes('w-full').bind_value(self.table, 'filter')
                    self.table.on('rowClick', self.row_clicked, js_handler='(event, row) => emit(row.id)')
                    self.list_message = ui.label().classes('text-sm text-red-700')
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-6 gap-4'):
                    ui.label('교육/행사 일지').classes('text-xl font-bold')
                    ui.separator()
                    self.detail_message = ui.label('왼쪽 목록에서 교육/행사를 선택해 주세요.').classes('text-slate-500')
                    self.details = ui.column().classes('w-full gap-4')
        ui.timer(0.01, self.reload, once=True)

    async def row_clicked(self, event):
        await self.select_event(event.args)

    async def row_selected(self, event):
        await self.select_event(self.table.selected[0]['id'] if self.table.selected else None)

    async def reload(self):
        self.list_request += 1
        request = self.list_request
        self.list_message.text = ''
        self.table.props('loading')
        try:
            entries = []
            while True:
                batch = await run.io_bound(self.repository.list, limit=1000, offset=len(entries))
                if request != self.list_request:
                    return
                entries.extend(batch)
                if len(batch) < 1000:
                    break
            self.table.rows = [dict(id=e.id, title=e.title, category=e.category, event_date=e.event_date.isoformat()) for e in entries]
            self.table.selected = [r for r in self.table.rows if self.selected and r['id'] == self.selected.id]
            self.table.update()
        except DatabaseError as error:
            if request == self.list_request:
                self.list_message.text = str(error)
        finally:
            if request == self.list_request:
                self.table.props(remove='loading')

    def sync_selection(self):
        self.table.selected = [r for r in self.table.rows if self.selected and r['id'] == self.selected.id]
        self.table.update()

    async def select_event(self, event_id):
        if not await self.confirm_editor_discard():
            self.sync_selection()
            return
        self.selection_request += 1
        request = self.selection_request
        try:
            entry = await run.io_bound(self.repository.get, event_id) if event_id is not None else None
        except DatabaseError as error:
            if request == self.selection_request:
                self.detail_message.text = str(error)
                self.sync_selection()
            return
        if request != self.selection_request:
            return
        self.selected = entry
        self.sync_selection()
        self.clear_editor()
        self.detail_message.text = '' if entry else '왼쪽 목록에서 교육/행사를 선택해 주세요.'
        if entry is not None:
            self.build_editor(entry)

    async def after_deleted(self):
        await self.select_event(None)
        await self.reload()

    async def open_editor(self, entry=None):
        if not await self.confirm_editor_discard():
            return
        self.selection_request += 1
        self.selected = entry
        self.sync_selection()
        self.clear_editor()
        self.detail_message.text = ''
        self.build_editor(entry)

    def build_editor(self, entry=None):
        request = self.selection_request
        initial = entry.model_dump() if entry else dict(title='', category='교육',
            event_date=datetime.now(KST).date(), event_time='09:00', duration_minutes=60, location='', audience='', facilitator='', content='')
        with self.details:
            ui.label('교육/행사 수정' if entry else '새 교육/행사 등록').classes('text-2xl font-bold')
            fields = {}
            fields['title'] = ui.input('교육/행사명 *', value=initial['title']).props('outlined maxlength=200').classes('w-full')
            with ui.row().classes('w-full items-start flex-wrap'):
                fields['category'] = ui.select(['교육', '행사', '단체심리검사'], label='구분', value=initial['category']).props('outlined').classes('grow')
                fields['event_date'] = ui.date_input('날짜 *', value=initial['event_date'].isoformat()).props('outlined').classes('grow')
                fields['event_time'] = time_input('시각', value=initial['event_time']).props('outlined').classes('w-40')
                fields['duration_minutes'] = ui.number('운영 시간(분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-36')
            for key, label, maximum in [('location', '장소', 200), ('audience', '대상', 200), ('facilitator', '담당자 / 강사', 100)]:
                fields[key] = ui.input(label, value=initial[key]).props(f'outlined maxlength={maximum}').classes('w-full')
            fields['participant_count'] = ui.number('참여인원(명)', value=initial.get('participant_count'), min=0, max=2147483647, step=1).props('outlined clearable').classes('w-full')
            ui.label('상세 내용').classes('font-semibold')
            fields['content'] = ui.editor(value=editor_html(initial['content'], initial.get('content_format', 'text')),
                                          placeholder='상세 내용을 입력하세요.').classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            with ui.row() as attachments:
                attachment_button(self.repository.database, 'education', entry.id if entry else None)
            message = ui.label().classes('text-sm text-red-700')
            with ui.row().classes('w-full justify-end'):
                cancel_button = ui.button('작성 닫기').props('flat')
                save_button = ui.button('저장', icon='save')

        self.editor_fields = fields
        self.editor_original = self.editor_values()

        async def cancel():
            if request != self.selection_request or not await self.confirm_editor_discard():
                return
            self.selection_request += 1
            self.selected = None
            self.sync_selection()
            self.clear_editor()
            self.detail_message.text = '왼쪽 목록에서 교육/행사를 선택해 주세요.'

        async def save():
            nonlocal entry
            if self.editor_saving or request != self.selection_request:
                return
            try:
                data = {key: field.value for key, field in fields.items()}
                data['event_time'] = storage_time(data['event_time'])
                data['content'] = clean_html(data['content'] or '')
                value = EducationEventInput(**data, content_format='html')
            except (ValueError, TypeError):
                message.text = '교육/행사명, 날짜, 시각(오전/오후 hh:mm), 운영 시간(1~1440분 정수), 참여인원(0 이상 정수), 내용 길이(서식 포함 최대 20,000자)를 확인해 주세요.'
                return
            self.editor_saving = True
            controls = (*fields.values(), save_button, cancel_button)
            for control in controls:
                control.disable()
            try:
                entry = await run.io_bound(self.repository.save, value, entry.id if entry else None)
            except DatabaseError as error:
                message.text = str(error)
            else:
                self.selected = entry
                self.editor_original = self.editor_values()
                attachments.clear()
                with attachments:
                    attachment_button(self.repository.database, 'education', entry.id)
                message.text = '교육/행사를 저장했습니다.'
                await self.reload()
                ui.notify('교육/행사를 저장했습니다.', type='positive')
            finally:
                self.editor_saving = False
                for control in controls:
                    control.enable()

        cancel_button.on_click(cancel)
        save_button.on_click(save)
