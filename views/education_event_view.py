"""교육/행사 목록과 선택 항목의 상세 내용을 나란히 표시한다."""
from datetime import datetime

from nicegui import run, ui
from pydantic import ValidationError

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

    def build(self):
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('교육/행사').classes('text-3xl font-bold text-slate-800')
            ui.label('목록에서 교육/행사를 선택하여 상세 내용을 확인하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[2fr_3fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('교육/행사 목록').classes('text-xl font-bold')
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
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('교육/행사 상세').classes('text-xl font-bold')
                        self.edit = ui.button('정보 수정', icon='edit', on_click=lambda: self.open_editor(self.selected)).props('outline')
                        self.edit.disable()
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

    async def select_event(self, event_id):
        self.selection_request += 1
        request = self.selection_request
        self.selected = None
        self.edit.disable()
        self.details.clear()
        self.detail_message.text = '상세 내용을 불러오는 중입니다…'
        try:
            entry = await run.io_bound(self.repository.get, event_id) if event_id is not None else None
        except DatabaseError as error:
            if request == self.selection_request:
                self.detail_message.text = str(error)
            return
        if request != self.selection_request:
            return
        self.selected = entry
        self.table.selected = [r for r in self.table.rows if entry and r['id'] == entry.id]
        self.table.update()
        self.detail_message.text = '' if entry else '왼쪽 목록에서 교육/행사를 선택해 주세요.'
        if entry is None:
            return
        self.edit.enable()
        with self.details:
            ui.badge(entry.category).props('outline')
            ui.label(entry.title).classes('text-2xl font-bold break-words w-full')
            with ui.element('div').classes('w-full grid grid-cols-1 sm:grid-cols-2 gap-4'):
                for label, value in [('날짜', entry.event_date.isoformat()), ('시각', entry.event_time),
                                     ('운영 시간', f'{entry.duration_minutes}분' if entry.duration_minutes is not None else ''),
                                     ('장소', entry.location),
                                     ('대상', entry.audience), ('담당자 / 강사', entry.facilitator)]:
                    with ui.column().classes('gap-1 min-w-0'):
                        ui.label(label).classes('text-sm text-slate-500')
                        ui.label(value or '미입력').classes('whitespace-pre-wrap break-words w-full')
            ui.separator()
            ui.label('상세 내용').classes('font-bold')
            if entry.content:
                ui.html(editor_html(entry.content, entry.content_format)).classes('w-full break-words leading-relaxed')
            else:
                ui.label('등록된 상세 내용이 없습니다.').classes('text-slate-500')

    def open_editor(self, entry=None):
        initial = entry.model_dump() if entry else dict(title='', category='교육',
            event_date=datetime.now(KST).date(), event_time='09:00', duration_minutes=60, location='', audience='', facilitator='', content='')
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl p-6'):
            ui.label('교육/행사 수정' if entry else '새 교육/행사 등록').classes('text-2xl font-bold')
            fields = {}
            fields['title'] = ui.input('교육/행사명 *', value=initial['title']).props('outlined maxlength=200').classes('w-full')
            with ui.row().classes('w-full items-start'):
                fields['category'] = ui.select(['교육', '행사', '단체심리검사'], label='구분', value=initial['category']).props('outlined').classes('w-40')
                fields['event_date'] = ui.date_input('날짜 *', value=initial['event_date'].isoformat()).props('outlined').classes('grow min-w-40')
                fields['event_time'] = ui.time_input('시각', value=initial['event_time']).props('outlined').classes('w-32')
                fields['duration_minutes'] = ui.number('운영 시간(분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-36')
            for key, label, maximum in [('location', '장소', 200), ('audience', '대상', 200), ('facilitator', '담당자 / 강사', 100)]:
                fields[key] = ui.input(label, value=initial[key]).props(f'outlined maxlength={maximum}').classes('w-full')
            ui.label('상세 내용').classes('font-semibold')
            fields['content'] = ui.editor(value=editor_html(initial['content'], initial.get('content_format', 'text')),
                                          placeholder='상세 내용을 입력하세요.').classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            message = ui.label().classes('text-sm text-red-700')
            with ui.row().classes('w-full justify-end'):
                ui.button('취소', on_click=dialog.close).props('flat')
                save_button = ui.button('저장', icon='save')

        async def save():
            try:
                data = {key: field.value for key, field in fields.items()}
                data['content'] = clean_html(data['content'] or '')
                value = EducationEventInput(**data, content_format='html')
            except ValidationError:
                message.text = '교육/행사명, 날짜, 시각(HH:MM), 운영 시간(1~1440분 정수), 내용 길이(서식 포함 최대 20,000자)를 확인해 주세요.'
                return
            save_button.disable()
            try:
                saved = await run.io_bound(self.repository.save, value, entry.id if entry else None)
            except DatabaseError as error:
                message.text = str(error)
                save_button.enable()
                return
            dialog.close()
            await self.reload()
            await self.select_event(saved.id)
            ui.notify('교육/행사를 저장했습니다.', type='positive')

        save_button.on_click(save)
        dialog.on('hide', dialog.delete)
        dialog.open()
