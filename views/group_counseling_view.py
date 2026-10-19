"""집단 목록, 선택 집단의 상세 정보와 회기별 상담일지."""

from datetime import datetime
from collections.abc import Awaitable, Callable

from nicegui import run, ui

from database import DatabaseError
from models import GroupCounseling, GroupCounselingInput, GroupLogInput
from repositories.group_counseling_repo import GroupCounselingRepository
from repositories.student_repo import StudentRepository
from views.counseling_content import clean_html
from views.counseling_view import KST

PAGE_SIZE = 20


class GroupCounselingView:
    def __init__(self, repository: GroupCounselingRepository,
                 on_saved: Callable[[], Awaitable[None]] | None = None):
        self.repository = repository
        self.students = StudentRepository(repository.database)
        self.on_saved = on_saved
        self.selected: GroupCounseling | None = None
        self.list_request = 0
        self.selection_request = 0
        self.log_request = 0
        self.log_offset = 0
        self.editor_open = False

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('집단 상담').classes('text-3xl font-bold text-slate-800')
            ui.label('집단을 선택하고 상세 정보와 상담 일지를 관리하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 목록').classes('text-xl font-bold')
                        ui.button('집단 추가', icon='group_add', on_click=lambda: self.open_editor())
                    self.table = ui.table(columns=[
                        dict(name=key, label=label, field=key, align='left')
                        for key, label in [('name', '집단명'), ('facilitator', '진행자')]
                    ], rows=[], row_key='id', pagination=10).classes('w-full').props(
                        'flat no-data-label="등록된 집단 상담이 없습니다" no-results-label="검색 결과가 없습니다"')
                    with self.table.add_slot('top'):
                        ui.input('집단 검색').props('outlined dense clearable debounce=300').classes('w-full').bind_value(self.table, 'filter')
                    self.table.on('rowClick', self.row_clicked, js_handler='(event, row) => emit(row.id)')
                    self.list_message = ui.label().classes('text-sm text-red-700')
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5 gap-4'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 상세 정보').classes('text-xl font-bold')
                        self.edit = ui.button('정보 수정', icon='edit', on_click=lambda: self.open_editor(edit_group=True))
                        self.edit.disable()
                    self.details = ui.column().classes('w-full gap-3')
                    self.detail_message = ui.label('왼쪽 목록에서 집단을 선택해 주세요.').classes('text-slate-500')
                    ui.separator().classes('my-2')
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('집단 상담 일지 목록').classes('text-xl font-bold')
                        self.add_log = ui.button('새 집단 상담 일지', icon='edit_note', on_click=lambda: self.open_editor(log=True))
                        self.add_log.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.log_message = ui.label().classes('text-sm text-slate-500')
                    with ui.row().classes('w-full justify-end items-center'):
                        self.previous = ui.button('이전', on_click=lambda: self.log_page(-1)).props('flat')
                        self.page_label = ui.label()
                        self.next = ui.button('다음', on_click=lambda: self.log_page(1)).props('flat')
                        self.previous.disable()
                        self.next.disable()
        ui.timer(0.01, self.load_groups, once=True)

    async def row_clicked(self, event) -> None:
        await self.select_group(event.args)

    async def load_groups(self) -> None:
        self.list_request += 1
        request = self.list_request
        self.list_message.text = ''
        self.table.props('loading')
        try:
            groups = []
            while True:
                batch = await run.io_bound(self.repository.list, limit=1000, offset=len(groups))
                if request != self.list_request:
                    return
                groups.extend(batch)
                if len(batch) < 1000:
                    break
            self.table.rows = [dict(id=g.id, name=g.name, facilitator=g.facilitator or '미입력') for g in groups]
            self.table.update()
        except DatabaseError as error:
            if request == self.list_request:
                self.list_message.text = str(error)
        finally:
            if request == self.list_request:
                self.table.props(remove='loading')

    async def select_group(self, group_id: int) -> None:
        self.selection_request += 1
        request = self.selection_request
        self.log_request += 1
        self.selected = None
        self.details.clear()
        self.logs.clear()
        self.edit.disable()
        self.add_log.disable()
        self.previous.disable()
        self.next.disable()
        self.log_message.text = self.page_label.text = ''
        self.detail_message.text = '집단 상담 정보를 불러오는 중입니다…'
        try:
            group = await run.io_bound(self.repository.get, group_id)
        except DatabaseError as error:
            if request == self.selection_request:
                self.detail_message.text = str(error)
            return
        if request != self.selection_request:
            return
        if group is None:
            self.detail_message.text = '집단 상담을 찾을 수 없습니다. 다른 집단을 선택해 주세요.'
            return
        self.selected = group
        self.detail_message.text = ''
        with self.details:
            ui.label(group.name).classes('text-xl font-semibold')
            for label, value in [('진행자', group.facilitator), ('운영 기간', group.period),
                                 ('상담 영역', group.counseling_area), ('상담 목표', group.purpose), ('참여 학생', group.participant_labels),
                                 ('비고', group.notes)]:
                with ui.column().classes('gap-1 w-full'):
                    ui.label(f'참여 학생 ({len(group.student_ids)}명)' if label == '참여 학생' else label).classes('font-semibold text-slate-600')
                    if label == '참여 학생':
                        if value:
                            with ui.row().classes('w-full flex-wrap gap-2'):
                                for participant in value:
                                    ui.chip(participant, icon='person', color='teal-1', text_color='teal-9')
                        else:
                            ui.label('연결된 참여 학생이 없습니다.').classes('text-slate-500')
                    else:
                        ui.label(value or '미입력').classes('whitespace-pre-wrap break-words w-full')
        self.edit.enable()
        self.add_log.enable()
        self.log_offset = 0
        await self.load_logs()

    async def log_page(self, direction: int) -> None:
        self.log_offset = max(0, self.log_offset + direction * PAGE_SIZE)
        await self.load_logs()

    async def load_logs(self) -> None:
        if self.selected is None:
            return
        self.log_request += 1
        request = self.log_request
        self.logs.clear()
        self.previous.disable()
        self.next.disable()
        self.log_message.text = '상담 일지를 불러오는 중입니다…'
        try:
            entries = await run.io_bound(self.repository.list_logs, self.selected.id,
                                         limit=PAGE_SIZE + 1, offset=self.log_offset)
        except DatabaseError as error:
            if request == self.log_request:
                self.log_message.text = str(error)
            return
        if request != self.log_request:
            return
        with self.logs:
            for entry in entries[:PAGE_SIZE]:
                with ui.row().classes('w-full items-center justify-between border rounded-xl p-4'):
                    with ui.column().classes('gap-1'):
                        ui.label(entry.title).classes('font-semibold')
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    ui.button('열기 / 수정', icon='edit', on_click=lambda log_id=entry.id: self.open_editor(log=True, log_id=log_id)).props('outline')
        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 집단 상담 일지가 없습니다.'
        self.page_label.text = f'{self.log_offset // PAGE_SIZE + 1} 페이지'
        self.previous.set_enabled(self.log_offset > 0)
        self.next.set_enabled(len(entries) > PAGE_SIZE)

    async def open_editor(self, *, edit_group: bool = False, log: bool = False, log_id: int | None = None) -> None:
        if self.editor_open or ((edit_group or log) and self.selected is None):
            return
        self.editor_open = True
        group = self.selected if edit_group or log else None
        dialog = None
        try:
            entry = await run.io_bound(self.repository.get_log, log_id) if log_id is not None else None
            if log_id is not None and (entry is None or entry.group_id != group.id):
                ui.notify('이 집단의 상담 일지를 찾을 수 없습니다.', type='warning')
                return
            student_options = {}
            if not log:
                offset = 0
                while True:
                    students = await run.io_bound(self.students.list, limit=1000, offset=offset)
                    student_options.update({student.id: f'{student.name} · {student.grade}학년 {student.classroom}반 · 번호 {student.student_number or "미입력"}' for student in students})
                    if len(students) < 1000:
                        break
                    offset += len(students)
            fields = {}
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-5xl p-6 gap-4'):
                    ui.label(('집단 상담 일지 수정' if entry else '새 집단 상담 일지') if log else ('집단 정보 수정' if group else '새 집단 상담')).classes('text-2xl font-bold')
                    if log:
                        ui.label(group.name).classes('text-slate-500')
                        local_start = entry.starts_at.astimezone(KST) if entry else datetime.now(KST).replace(second=0, microsecond=0)
                        fields['title'] = ui.input('일지 제목', value=entry.title if entry else '').props('outlined maxlength=200').classes('w-full')
                        with ui.row().classes('w-full'):
                            fields['starts_on'] = ui.date_input('상담 날짜', value=local_start.date().isoformat()).props('outlined')
                            fields['starts_time'] = ui.time_input('시작 시각 (한국 시각)', value=local_start.time().isoformat()).props('outlined')
                            fields['duration_minutes'] = ui.number('상담 시간 (분)', value=entry.duration_minutes if entry else 50, min=1, max=1440, step=1).props('outlined')
                        ui.label('상담 내용').classes('font-semibold')
                        fields['content_html'] = ui.editor(value=clean_html(entry.content_html) if entry else '').classes('w-full').props("""min-height=320px :toolbar='[[{"label": "머릿말", "list": "no-icons", "options": ["p", "h1", "h2", "h3"]}], ["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
                        fields['follow_up'] = ui.textarea('후속 조치', value=entry.follow_up if entry else '').props('outlined maxlength=20000').classes('w-full')
                    else:
                        fields['name'] = ui.input('집단명', value=group.name if group else '').props(
                            'outlined maxlength=200').classes('w-full')
                        with ui.row().classes('w-full'):
                            fields['facilitator'] = ui.input('진행자', value=group.facilitator if group else '').props('outlined maxlength=100').classes('grow')
                            fields['period'] = ui.date_input('운영 기간', range_input=True, value=group.period if group else '').props('outlined').classes('grow')
                            fields['counseling_area'] = ui.select(['학업', '진로', '학교폭력', '성격/대인관계', '기타'], label='상담 영역', value=group.counseling_area or None if group else None).props('outlined').classes('grow')
                        if group and group.participants:
                            fields['participants'] = ui.textarea('기존 참여자 메모', value=group.participants).props(
                                'outlined maxlength=20000').classes('w-full')
                        fields['purpose'] = ui.textarea('상담 목표', value=group.purpose if group else '').props(
                            'outlined maxlength=20000').classes('w-full')
                        fields['student_ids'] = ui.select(student_options, label='참여 학생', multiple=True,
                                                         value=list(group.student_ids) if group else [], with_input=True).props(
                            'outlined use-chips').classes('w-full')
                        ui.label('연결한 학생의 타임라인에 이 집단의 모든 상담 일지가 표시됩니다.').classes('text-sm text-slate-500')
                        fields['notes'] = ui.textarea('비고', value=group.notes if group else '').props(
                            'outlined maxlength=20000').classes('w-full')
                    message = ui.label().classes('text-red-700 text-sm')
                    with ui.row().classes('w-full justify-end'):
                        cancel_button = ui.button('작성 닫기').props('flat')
                        save_button = ui.button('저장', icon='save')
            original = {key: list(field.value) if isinstance(field.value, list) else field.value for key, field in fields.items()}
            saving = False

            async def cancel():
                if saving:
                    return
                if original != {key: field.value for key, field in fields.items()}:
                    with ui.dialog().props('persistent') as confirm, ui.card():
                        ui.label('저장하지 않은 내용을 버릴까요?')
                        ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                        ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                    discard = await confirm
                    confirm.delete()
                    if not discard:
                        return
                dialog.submit(None)

            async def save():
                nonlocal saving
                if saving:
                    return
                data = {key: field.value for key, field in fields.items()}
                try:
                    if log:
                        data['starts_at'] = datetime.fromisoformat(f"{data.pop('starts_on')}T{data.pop('starts_time')}")
                        if data['starts_at'].tzinfo is not None:
                            raise ValueError('한국 시각을 입력하세요.')
                        data['starts_at'] = data['starts_at'].replace(tzinfo=KST)
                        data['content_html'] = clean_html(data['content_html'] or '')
                        value = GroupLogInput(group_id=group.id, **data)
                    else:
                        data['student_ids'] = data.get('student_ids') or []
                        data['period'] = data.get('period') or ''
                        data['counseling_area'] = data.get('counseling_area') or ''
                        value = GroupCounselingInput(**data)
                except (ValueError, TypeError):
                    message.text = ('일지 제목, 날짜·시각, 상담 시간(1~1440분)과 입력 길이를 확인해 주세요.' if log else
                                    '집단명과 입력 길이를 확인해 주세요. 운영 기간은 YYYY-MM-DD 또는 YYYY-MM-DD - YYYY-MM-DD 형식이며 종료일은 시작일 이후여야 합니다.')
                    return
                saving = True
                for field in (*fields.values(), save_button, cancel_button):
                    field.disable()
                try:
                    if log:
                        saved = await run.io_bound(self.repository.save_log, value, log_id)
                    else:
                        saved = await run.io_bound(self.repository.save, value, group.id if group else None)
                    dialog.submit(saved)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for field in (*fields.values(), save_button, cancel_button):
                        field.enable()

            save_button.on_click(save)
            cancel_button.on_click(cancel)
            saved = await dialog
            if saved:
                ui.notify('저장했습니다.', type='positive')
                if log:
                    if self.selected and self.selected.id == group.id:
                        self.log_offset = 0
                        await self.load_logs()
                else:
                    await self.load_groups()
                    if group is None or (self.selected and self.selected.id == group.id):
                        await self.select_group(saved.id)
                if self.on_saved:
                    await self.on_saved()
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
