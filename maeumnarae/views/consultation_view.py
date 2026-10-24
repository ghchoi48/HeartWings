"""자문 페이지의 교사 목록, 교사 정보 편집 및 자문 일지 목록 영역."""

from datetime import date, datetime, timedelta, timezone

from maeumnarae.views.journal_pagination import PAGE_SIZE, load_page

from nicegui import run, ui

from maeumnarae.views.attachment_view import attachment_button

from maeumnarae.views.delete_action import delete_button
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import CONSULTATION_AREAS, Teacher, TeacherInput, Consultation, ConsultationInput
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.views.counseling_content import clean_html
from maeumnarae.views.time_inputs import parse_time, time_input

KST = timezone(timedelta(hours=9))
STATUSES = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}


class ConsultationView:
    def __init__(self, teachers: TeacherRepository):
        self.teachers = teachers
        self.consultations = ConsultationRepository(teachers.database)
        self.log_request = 0
        self.log_offset = 0
        self.selected: Teacher | None = None
        self.list_request = 0
        self.selection_request = 0
        self.editor_open = False

    def build(self) -> None:
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('자문').classes('text-3xl font-bold text-slate-800')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('교사 목록').classes('text-xl font-bold')
                        ui.button('교사 추가', icon='person_add', on_click=lambda: self.open_editor())
                    self.table = ui.table(columns=[
                        {'name': key, 'label': label, 'field': key, 'align': 'left'}
                        for key, label in [('name', '이름'), ('extension', '내선번호'), ('responsibilities', '담당업무')]
                    ], rows=[], row_key='id', pagination={
                        'rowsPerPage': 10, 'sortBy': 'name', 'descending': False, 'page': 1,
                    }).classes('w-full').props(
                        'flat :rows-per-page-options="[10, 20, 30]" rows-per-page-label="페이지당 교사 수" '
                        'no-data-label="등록된 교사가 없습니다" no-results-label="검색 결과가 없습니다"')
                    with self.table.add_slot('top'):
                        ui.input('교사 검색', placeholder='이름, 내선번호, 담당업무').props(
                            'outlined dense clearable debounce=300').classes('w-full').bind_value(self.table, 'filter')
                    self.table.on('rowClick', self.row_clicked, js_handler='(event, row) => emit(row.id)')
                self.log_panel = ui.column().classes('w-full min-w-0')
                self.show_logs()
            ui.timer(0.01, self.reload, once=True)

    async def reload(self) -> None:
        self.list_request += 1
        request = self.list_request
        self.table.rows = []
        self.table.props('loading')
        try:
            teachers = []
            while True:
                batch = await run.io_bound(self.teachers.list, limit=1000, offset=len(teachers))
                if request != self.list_request:
                    return
                teachers.extend(batch)
                if len(batch) < 1000:
                    break
            self.table.rows = [dict(id=t.id, name=t.name, extension=t.extension or '—',
                                   responsibilities=t.responsibilities or '—')
                               for t in teachers]
            self.table.update()
        except DatabaseError as error:
            if request == self.list_request:
                ui.notify(str(error), type='negative')
        finally:
            if request == self.list_request:
                self.table.props(remove='loading')

    async def row_clicked(self, event) -> None:
        await self.select_teacher(event.args)

    async def select_teacher(self, teacher_id: int) -> None:
        self.selection_request += 1
        self.log_request += 1
        self.log_offset = 0
        request = self.selection_request
        self.selected = None
        self.show_logs()
        try:
            teacher = await run.io_bound(self.teachers.get, teacher_id)
        except DatabaseError as error:
            if request == self.selection_request:
                ui.notify(str(error), type='negative')
            return
        if request == self.selection_request:
            self.selected = teacher
            self.show_logs()
            await self.load_logs()

    def show_logs(self) -> None:
        """교사 선택에 맞춰 일지 목록 영역을 초기화한다."""
        self.log_panel.clear()
        with self.log_panel, ui.card().classes('w-full rounded-2xl shadow-sm p-5'):
            teacher = self.selected
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(f'{teacher.name} 선생님' if teacher else '목록에서 교사를 선택해 주세요.').classes('text-xl font-bold')
                ui.space()
                delete_button(self.teachers.database, 'teacher', lambda: self.selected,
                              self.after_teacher_deleted, blocked=lambda: self.editor_open).bind_visibility_from(
                                  self, 'selected', backward=lambda value: value is not None)
                self.edit_teacher = ui.button('교사 정보 수정', icon='edit',
                                              on_click=lambda: self.open_editor(self.selected)).props('outline')
                self.edit_teacher.set_enabled(teacher is not None)
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('자문 일지 목록').classes('text-lg font-bold')
                self.add_log = ui.button('새 자문 일지', icon='edit_note', on_click=lambda: self.open_log_editor())
                self.add_log.set_enabled(teacher is not None)
            self.logs = ui.column().classes('w-full gap-3')
            self.log_message = ui.label().classes('text-sm text-slate-500')
            with ui.row().classes('w-full items-center justify-end'):
                self.previous = ui.button('일지 이전', on_click=lambda: self.log_page(-1)).props('flat')
                self.page_label = ui.label()
                self.next = ui.button('일지 다음', on_click=lambda: self.log_page(1)).props('flat')
            self.previous.disable()
            self.next.disable()

    async def after_teacher_deleted(self):
        self.selection_request += 1
        self.log_request += 1
        self.selected = None
        self.show_logs()
        await self.reload()

    async def after_log_deleted(self):
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
        self.page_label.text = ''
        self.log_message.text = '자문 일지를 불러오는 중입니다…'
        try:
            entries, offset, pages = await run.io_bound(
                load_page, self.consultations.list, self.consultations.count, self.log_offset,
                self.selected.id)
        except DatabaseError as error:
            if request == self.log_request:
                self.log_message.text = str(error)
            return
        if request != self.log_request:
            return
        self.log_offset = offset
        with self.logs:
            for entry in entries[:PAGE_SIZE]:
                open_log = lambda entry_id=entry.id: self.open_log_editor(entry_id)
                with ui.row().classes(
                        'w-full items-center justify-between border rounded-xl p-4 cursor-pointer hover:bg-slate-50 focus-visible:outline'
                ).props('role=button tabindex=0 aria-label="일지 열기"').on('click', open_log).on(
                        'keydown.enter.self.prevent', open_log).on('keydown.space.self.prevent', open_log):
                    with ui.column().classes('gap-1'):
                        ui.label(entry.consultation_area or '자문 분야 미지정').classes('font-semibold')
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {STATUSES[entry.status]} · 자문 · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    delete_button(self.teachers.database, 'consultation', lambda entry=entry: entry, self.after_log_deleted, blocked=lambda: self.editor_open, icon_only=True)

        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 자문 일지가 없습니다. 새 자문 일지를 작성해 보세요.'
        self.page_label.text = f'{self.log_offset // PAGE_SIZE + 1}페이지/{pages}페이지'
        self.previous.set_enabled(self.log_offset > 0)
        self.next.set_enabled(self.log_offset // PAGE_SIZE + 1 < pages)

    async def open_log_editor(self, entry_id: int | None = None) -> None:
        if self.editor_open or self.selected is None:
            return
        self.editor_open = True
        teacher = self.selected
        dialog = None
        saving = False
        try:
            entry = None
            if entry_id is not None:
                try:
                    entry = await run.io_bound(self.consultations.get, entry_id, teacher.id)
                except DatabaseError as error:
                    ui.notify(str(error), type='negative')
                    return
                if entry is None:
                    ui.notify('자문 일지를 찾을 수 없습니다.', type='warning')
                    return
            with self.log_panel.client.content:
                dialog, fields, message, save_button, cancel_button = self.build_log_editor(teacher, entry)
            original = {key: field.value for key, field in fields.items()}

            async def cancel():
                if saving:
                    return
                if original != {key: field.value for key, field in fields.items()}:
                    with self.log_panel.client.content:
                        with ui.dialog().props('persistent') as confirm, ui.card():
                            ui.label('저장하지 않은 내용을 버릴까요?')
                            ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                            ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                    discard = await confirm
                    confirm.delete()
                    if not discard:
                        return
                dialog.submit(False)

            async def save():
                nonlocal saving
                if saving:
                    return
                try:
                    data = {key: field.value for key, field in fields.items()}
                    starts_at = datetime.combine(date.fromisoformat(data.pop('starts_on')),
                                                 parse_time(data.pop('starts_time')))
                    if starts_at.tzinfo is not None:
                        raise ValueError('한국 시각으로 입력해 주세요.')
                    if data['consultation_area'] not in CONSULTATION_AREAS:
                        message.text = '자문 분야를 선택해 주세요.'
                        return
                    data['title'] = data['consultation_area']
                    data['content_html'] = clean_html(data['content_html'] or '')
                    value = ConsultationInput(teacher_id=teacher.id, starts_at=starts_at.replace(tzinfo=KST), **data)
                except (ValueError, TypeError):
                    message.text = '자문 분야, 날짜·시각, 자문 시간(1~1440분)과 입력 길이를 확인해 주세요.'
                    return
                saving = True
                for field in (*fields.values(), save_button, cancel_button):
                    field.disable()
                try:
                    await run.io_bound(self.consultations.save, value, entry_id)
                    dialog.submit(True)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for field in (*fields.values(), save_button, cancel_button):
                        field.enable()

            save_button.on_click(save)
            cancel_button.on_click(cancel)
            if await dialog:
                ui.notify('자문 일지를 저장했습니다.', type='positive')
                if self.selected and self.selected.id == teacher.id:
                    self.log_offset = 0
                    await self.load_logs()
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    def build_log_editor(self, teacher: Teacher, entry: Consultation | None):
        initial = entry.model_dump() if entry else dict(starts_at=datetime.now(KST).replace(second=0, microsecond=0),
            duration_minutes=30, status='scheduled', consultation_area='', content_html='', follow_up='')
        local_start = initial['starts_at'].astimezone(KST)
        fields = {}
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6 gap-4'):
            ui.label('자문 일지 수정' if entry else '새 자문 일지 작성').classes('text-2xl font-bold')
            ui.label(f'{teacher.name} 선생님').classes('text-slate-500')
            fields['consultation_area'] = ui.select(CONSULTATION_AREAS, label='자문 분야',
                value=initial['consultation_area'] or None).props('outlined').classes('w-full')
            with ui.row().classes('w-full items-start'):
                fields['starts_on'] = ui.date_input('자문 날짜', value=local_start.date().isoformat()).props('outlined').classes('grow')
                fields['starts_time'] = time_input('시작 시각 (한국 시각)', value=local_start.time().isoformat()).props('outlined').classes('grow')
                fields['duration_minutes'] = ui.number('자문 시간 (분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-36')
                fields['status'] = ui.select(STATUSES, label='자문 상태', value=initial['status']).props('outlined').classes('w-36')
            ui.label('자문 내용').classes('font-semibold')
            fields['content_html'] = ui.editor(value=clean_html(initial['content_html']), placeholder='자문 내용을 입력하세요.').classes('w-full').props(
                """min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            fields['follow_up'] = ui.textarea('후속 조치', value=initial['follow_up']).props('outlined rows=2 maxlength=20000').classes('w-full')
            message = ui.label().classes('text-sm text-red-700')
            with ui.row().classes('w-full items-center'):
                attachment_button(self.teachers.database, 'consultation', entry.id if entry else None)
                ui.space()
                cancel = ui.button('취소').props('flat')
                save = ui.button('일지 저장', icon='save')
        return dialog, fields, message, save, cancel

    async def open_editor(self, teacher: Teacher | None = None) -> None:
        if self.editor_open:
            return
        self.editor_open = True
        dialog = None
        saving = False
        try:
            with self.log_panel.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-lg p-6'):
                    ui.label('교사 정보 수정' if teacher else '교사 추가').classes('text-2xl font-bold')
                    fields = {}
                    for key, label, length in [('name', '이름 (필수)', 100), ('contact', '연락처', 200),
                                               ('extension', '내선번호', 50), ('responsibilities', '담당업무', 200)]:
                        fields[key] = ui.input(label, value=getattr(teacher, key) if teacher else '').props(
                            f'outlined maxlength={length}').classes('w-full')
                    message = ui.label().classes('text-sm text-red-700')

                    async def save():
                        nonlocal saving
                        if saving:
                            return
                        try:
                            value = TeacherInput(**{key: field.value for key, field in fields.items()})
                        except ValidationError:
                            message.text = '이름을 입력하고 각 항목의 입력 길이를 확인해 주세요.'
                            return
                        saving = True
                        for element in (*fields.values(), save_button, cancel):
                            element.disable()
                        try:
                            saved = await run.io_bound(self.teachers.save, value, teacher.id if teacher else None)
                            dialog.submit(saved)
                        except DatabaseError as error:
                            message.text = str(error)
                        finally:
                            saving = False
                            for element in (*fields.values(), save_button, cancel):
                                element.enable()

                    with ui.row().classes('w-full justify-end'):
                        cancel = ui.button('취소', on_click=lambda: dialog.submit(None)).props('flat')
                        save_button = ui.button('저장', icon='save', on_click=save)
            saved = await dialog
            if saved is not None:
                await self.reload()
                await self.select_teacher(saved.id)
                ui.notify('교사 정보를 저장했습니다.', type='positive')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()
