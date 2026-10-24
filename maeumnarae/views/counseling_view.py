"""학생별 상담 일지 목록과 서식 편집/미리보기. SQL은 저장소에 위임한다."""

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone

from maeumnarae.views.journal_pagination import PAGE_SIZE, load_page

from nicegui import run, ui

from maeumnarae.views.attachment_view import attachment_button

from maeumnarae.views.delete_action import delete_button
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import Counseling, CounselingInput, Student, CounselingCase, CounselingCaseInput, GUARDIAN_COUNSELING_AREAS
from maeumnarae.repositories.case_repo import CaseRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.counseling_content import clean_html, editor_html
from maeumnarae.views.time_inputs import parse_time, time_input

KST = timezone(timedelta(hours=9))
COUNSELING_AREAS = ['학업', '진로', '성격', '성', '대인관계', '가정 및 가족관계', '일탈 및 비행',
                    '학교폭력 가해', '학교폭력 피해', '자해 및 자살', '정신건강',
                    '컴퓨터 및 스마트폰 과사용', '정보제공', '기타']
STATUSES = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}
TARGET_CATEGORIES = {'학생본인': '개인상담', '보호자(가족)': '학부모상담'}


def counseling_form_input(student_id: int, values: dict) -> CounselingInput:
    """화면의 한국 시각을 시간대가 포함된 모델로 바꾼다. HTML은 정화한다."""
    data = dict(values)
    if 'private_note_html' in data:
        data['private_note_html'] = clean_html(data['private_note_html'] or '')
    for key in ('counseling_method', 'counseling_target', 'counseling_area'):
        if key in data:
            data[key] = data[key] or ''
    if data.get('content_format') == 'html':
        data['content_markdown'] = clean_html(data.get('content_markdown') or '')
    if 'starts_on' in data or 'starts_time' in data:
        starts_at = datetime.combine(
            date.fromisoformat(data.pop('starts_on')),
            parse_time(data.pop('starts_time')),
        )
    else:
        starts_at = datetime.fromisoformat(data['starts_at'])
    if starts_at.tzinfo is not None:
        raise ValueError('상담 일시는 한국 시각으로 입력해 주세요.')
    data['starts_at'] = starts_at.replace(tzinfo=KST)
    if 'counseling_area' in data:
        data['title'] = data['counseling_area'] or '상담 분야 미지정'
    else:
        data.setdefault('title', '상담 분야 미지정')
    return CounselingInput(student_id=student_id, **data)


class CounselingView:
    """학생과 사례 선택, 상담 일지 목록과 인라인 편집 상태를 관리한다."""

    log_name = '상담 일지'

    def set_case_actions_enabled(self, enabled: bool) -> None:
        for button in (self.edit_case, self.intake_interview, self.closing_report):
            button.set_enabled(enabled)

    def __init__(self, students: StudentRepository, counseling: CounselingRepository,
                 on_saved: Callable[[int], Awaitable[None]] | None = None,
                 on_selected: Callable[[int | None], Awaitable[None]] | None = None):
        self.students = students
        self.counseling = counseling
        self.cases = CaseRepository(counseling.database)
        self.selected_case: CounselingCase | None = None
        self.case_request = 0
        self.case_options: dict[int, CounselingCase] = {}
        self.on_saved = on_saved
        self.on_selected = on_selected
        self.selected: Student | None = None
        self.log_offset = 0
        self.student_request = 0
        self.log_request = 0
        self.report_open = False
        self.editor_saving = False
        self.editor_request = 0
        self.editor_fields = {}
        self.editor_original = {}

    @property
    def editor_open(self) -> bool:
        return self.report_open or self.editor_saving or self.editor_dirty()

    def editor_dirty(self) -> bool:
        return self.editor_original != {key: field.value for key, field in self.editor_fields.items()}

    async def confirm_editor_discard(self) -> bool:
        if self.editor_saving or self.report_open:
            return False
        if not self.editor_dirty():
            return True
        with ui.context.client.content:
            with ui.dialog().props('persistent') as confirm, ui.card():
                ui.label('저장하지 않은 내용을 버릴까요?')
                with ui.row():
                    ui.button('계속 작성', on_click=lambda: confirm.submit(False)).props('flat')
                    ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True)).props('color=negative')
        try:
            return bool(await confirm)
        finally:
            if not confirm.is_deleted:
                confirm.delete()

    def clear_editor(self) -> None:
        self.editor_request += 1
        self.editor_fields = {}
        self.editor_original = {}
        self.editor_container.clear()
        with self.editor_container:
            ui.label('새 상담일지를 작성하거나, 상담일지를 선택해주세요').classes('text-slate-500')

    def build(self) -> None:
        """선택 학생의 상담 사례 목록과 사례별 일지를 구성한다."""
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            self.student_heading = ui.label('학생 관리에서 상담 대상 학생을 선택해 주세요.').classes('text-xl font-bold')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('상담 사례 목록').classes('text-lg font-bold')
                        with ui.row().classes('items-center gap-2'):
                            self.add_case = ui.button('새 상담 사례', icon='create_new_folder',
                                                      on_click=lambda: self.open_case_editor(report_field='intake_html'))
                            self.add_case.disable()
                    self.case_select = ui.select({}, label='상담 사례', on_change=self.change_case).props('outlined').classes('w-full')
                    self.case_select.disable()
                    self.case_message = ui.label().classes('text-sm text-slate-500')
                    ui.separator()
                    with ui.row().classes('w-full items-center justify-between'):
                        self.log_heading = ui.label('상담 일지 목록').classes('text-lg font-bold')
                        self.add = ui.button('새 상담 일지', icon='edit_note', on_click=lambda: self.open_editor())
                        self.add.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.log_message = ui.label().classes('text-sm text-slate-500')
                    with ui.row().classes('w-full items-center justify-end'):
                        self.log_previous = ui.button('일지 이전', on_click=lambda: self.log_page(-1)).props('flat')
                        self.log_page_label = ui.label()
                        self.log_next = ui.button('일지 다음', on_click=lambda: self.log_page(1)).props('flat')
                    self.log_previous.disable()
                    self.log_next.disable()
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center'):
                        self.intake_interview = ui.button('접수 면접', icon='assignment_ind',
                                                        on_click=lambda: self.open_case_editor(self.selected_case, 'intake_html')).props('outline')
                        self.intake_interview.disable()
                        self.edit_case = ui.button('사례 개념화 보고서', icon='description',
                                                   on_click=lambda: self.open_case_editor(self.selected_case)).props('outline')
                        self.edit_case.disable()
                        self.closing_report = ui.button('종결 보고서', icon='task_alt',
                                                      on_click=lambda: self.open_case_editor(self.selected_case, 'closing_html')).props('outline')
                        self.closing_report.disable()
                        ui.space()
                        delete_button(self.students.database, 'case', lambda: self.selected_case,
                                      self.after_case_deleted, blocked=lambda: self.editor_open)
                    ui.separator()
                    self.editor_container = ui.column().classes('w-full min-w-0 gap-4')
                    self.clear_editor()

    async def select_student(self, student_id: int | None) -> None:
        """상담 대상의 최신 프로필을 읽고 다른 학생의 이전 일지를 즉시 숨긴다."""
        if not await self.confirm_editor_discard():
            return
        self.clear_editor()
        self.student_request += 1
        self.log_request += 1
        request = self.log_request
        self.selected = None
        self.selected_case = None
        self.case_request += 1
        self.case_options = {}
        self.case_select.set_options({}, value=None)
        self.case_select.disable()
        self.set_case_actions_enabled(False)
        self.case_message.text = ''
        self.add_case.disable()
        self.logs.clear()
        self.log_message.text = ''
        self.log_page_label.text = ''
        self.student_heading.text = '상담 대상 학생을 선택해 주세요.'
        self.add.disable()
        self.log_previous.disable()
        self.log_next.disable()
        if self.on_selected:
            await self.on_selected(student_id)
            if request != self.log_request:
                return
        if student_id is None:
            return
        try:
            student = await run.io_bound(self.students.get, student_id)
        except DatabaseError as error:
            if request == self.log_request:
                self.log_message.text = str(error)
            return
        if request != self.log_request:
            return
        if student is None:
            self.log_message.text = '학생이 존재하지 않습니다. 학생 목록을 새로고침해 주세요.'
            return
        self.selected = student
        self.student_heading.text = f'{student.name} · {student.grade}학년 {student.classroom}반'
        self.add_case.enable()
        self.log_offset = 0
        await self.load_cases()

    async def after_case_deleted(self):
        self.clear_editor()
        self.log_offset = 0
        await self.load_cases()
        if self.on_saved and self.selected:
            await self.on_saved(self.selected.id)

    async def after_log_deleted(self):
        self.clear_editor()
        self.log_offset = 0
        await self.load_logs()
        if self.on_saved and self.selected:
            await self.on_saved(self.selected.id)

    async def load_cases(self, preferred_id: int | None = None) -> None:
        if self.selected is None:
            return
        if not await self.confirm_editor_discard():
            return
        self.clear_editor()
        self.case_request += 1
        request = self.case_request
        student_id = self.selected.id
        previous_id = preferred_id or (self.selected_case.id if self.selected_case else None)
        self.log_request += 1
        self.selected_case = None
        self.add.disable()
        self.logs.clear()
        self.case_options = {}
        self.case_select.set_options({}, value=None)
        self.case_select.disable()
        self.set_case_actions_enabled(False)
        self.log_previous.disable()
        self.log_next.disable()
        self.log_page_label.text = ''
        self.log_message.text = ''
        self.case_message.text = '상담 사례를 불러오는 중입니다…'
        try:
            cases = await run.io_bound(self.cases.list, student_id)
        except DatabaseError as error:
            if request == self.case_request:
                self.case_message.text = str(error)
            return
        if request != self.case_request:
            return
        self.case_options = {case.id: case for case in cases}
        self.case_select.set_options({case.id: case.title for case in cases})
        self.case_select.set_enabled(bool(cases))
        self.case_message.text = f'{len(cases)}개 사례 · 사례를 선택해 상담 일지를 확인하세요.' if cases else '등록된 사례가 없습니다. 새 상담 사례를 만들어 주세요.'
        if cases:
            await self.select_case(next((case for case in cases if case.id == previous_id), cases[0]))

    async def change_case(self) -> None:
        case = self.case_options.get(self.case_select.value)
        if case is not None and case != self.selected_case:
            await self.select_case(case)

    async def select_case(self, case: CounselingCase) -> None:
        if self.selected is None or case.student_id != self.selected.id:
            return
        if not await self.confirm_editor_discard():
            self.case_select.set_value(self.selected_case.id if self.selected_case else None)
            return
        self.clear_editor()
        self.selected_case = case
        if case.id in self.case_options:
            self.case_select.set_value(case.id)
        self.set_case_actions_enabled(True)
        self.log_offset = 0
        self.add.enable()
        await self.load_logs()

    async def open_case_editor(self, case: CounselingCase | None = None, report_field: str = 'report_html') -> None:
        if self.report_open or self.editor_saving or self.selected is None:
            return
        if case is not None and case.student_id != self.selected.id:
            return
        report_name, placeholder = {
            'report_html': ('사례 개념화 보고서', '주호소, 배경, 사례 이해, 상담 목표와 개입 계획 등을 작성하세요.'),
            'intake_html': ('접수 면접', '상담 신청 경위, 주호소, 배경 정보와 초기 면접 내용을 작성하세요.'),
            'closing_html': ('종결 보고서', '상담 진행 요약, 목표 달성 정도, 종결 사유와 추후 계획을 작성하세요.'),
        }[report_field]
        self.report_open = True
        student = self.selected
        dialog = None
        try:
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6 gap-4'):
                    ui.label(report_name if case else f'새 상담 사례 · {report_name}').classes('text-2xl font-bold')
                    ui.label(student.name).classes('text-slate-500')
                    title = ui.input('사례명', value=case.title if case else '').props('outlined maxlength=200').classes('w-full')
                    ui.label(report_name).classes('font-semibold')
                    report = ui.editor(value=clean_html(getattr(case, report_field)) if case else '',
                                       placeholder=placeholder).classes('w-full').props("""min-height=360px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel_button = ui.button('취소').props('flat')
                        save_button = ui.button('사례 저장', icon='save')
            original = (title.value, report.value)
            saving = False

            async def cancel():
                if saving:
                    return
                if (title.value, report.value) != original:
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
                try:
                    value = CounselingCaseInput(student_id=student.id, title=title.value,
                                                **{report_field: clean_html(report.value or '')})
                except (ValueError, TypeError):
                    message.text = '사례명(1~200자)과 보고서 길이(최대 200,000자)를 확인해 주세요.'
                    return
                saving = True
                for field in (title, report, save_button, cancel_button):
                    field.disable()
                try:
                    saved = await run.io_bound(self.cases.save, value, case.id if case else None, report_field)
                    dialog.submit(saved)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for field in (title, report, save_button, cancel_button):
                        field.enable()

            cancel_button.on_click(cancel)
            save_button.on_click(save)
            saved = await dialog
            self.report_open = False
            if saved:
                ui.notify(f'상담 사례와 {report_name} 내용을 저장했습니다.', type='positive')
                if self.selected and self.selected.id == student.id:
                    await self.load_cases(preferred_id=saved.id)
        finally:
            self.report_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def log_page(self, direction: int) -> None:
        """선택 학생의 상담 목록 페이지를 이동한다."""
        self.log_offset = max(0, self.log_offset + direction * PAGE_SIZE)
        await self.load_logs()

    async def load_logs(self) -> None:
        """선택 학생의 상담 목록을 최신순으로 읽는다."""
        if self.selected is None or self.selected_case is None:
            return
        self.log_request += 1
        request = self.log_request
        self.logs.clear()
        self.log_previous.disable()
        self.log_next.disable()
        self.log_message.text = '상담 일지를 불러오는 중입니다…'
        try:
            entries, offset, pages = await run.io_bound(
                load_page, self.counseling.list, self.counseling.count, self.log_offset,
                student_id=self.selected.id, case_id=self.selected_case.id)
        except DatabaseError as error:
            if request == self.log_request:
                self.log_message.text = str(error)
            return
        if request != self.log_request:
            return
        self.log_offset = offset
        with self.logs:
            for entry in entries[:PAGE_SIZE]:
                open_log = lambda entry_id=entry.id: self.open_editor(entry_id)
                with ui.row().classes(
                        'w-full items-center justify-between border rounded-xl p-4 cursor-pointer hover:bg-slate-50 focus-visible:outline'
                ).props('role=button tabindex=0 aria-label="일지 열기"').on('click', open_log).on(
                        'keydown.enter.self.prevent', open_log).on('keydown.space.self.prevent', open_log):
                    with ui.column().classes('gap-1'):
                        ui.label(entry.counseling_area or '상담 분야 미지정').classes('font-semibold')
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {STATUSES[entry.status]} · {entry.category} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    delete_button(self.students.database, 'counseling', lambda entry=entry: entry, self.after_log_deleted, blocked=lambda: self.editor_open, icon_only=True)

        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 상담 일지가 없습니다. 새 상담 일지를 작성해 보세요.'
        self.log_page_label.text = f'{self.log_offset // PAGE_SIZE + 1}페이지/{pages}페이지'
        self.log_previous.set_enabled(self.log_offset > 0)
        self.log_next.set_enabled(self.log_offset // PAGE_SIZE + 1 < pages)

    async def open_editor(self, entry_id: int | None = None) -> None:
        """오른쪽 카드에서 일지를 편집하며 저장 실패 시 입력을 보존한다."""
        if self.selected is None or self.selected_case is None:
            return
        if not await self.confirm_editor_discard():
            return
        self.editor_request += 1
        request = self.editor_request
        student, case = self.selected, self.selected_case
        entry = None
        if entry_id is not None:
            try:
                entry = await run.io_bound(self.counseling.get, entry_id)
            except DatabaseError as error:
                if request == self.editor_request:
                    ui.notify(str(error), type='negative')
                return
            if request != self.editor_request:
                return
            if entry is None or entry.student_id != student.id or entry.case_id != case.id:
                ui.notify('상담 일지를 찾을 수 없습니다. 목록을 새로고침해 주세요.', type='warning')
                return
        self.editor_container.clear()
        with self.editor_container:
            _, fields, message, save_button = self.build_editor(student, entry)
        self.editor_fields = fields
        self.editor_original = {key: field.value for key, field in fields.items()}

        async def save() -> None:
            nonlocal entry
            if self.editor_saving or request != self.editor_request:
                return
            target = fields['counseling_target'].value
            if target not in TARGET_CATEGORIES:
                message.text = '상담 대상을 학생본인 또는 보호자(가족) 중에서 선택해 주세요.'
                return
            fields['category'].value = TARGET_CATEGORIES[target]
            try:
                value = counseling_form_input(student.id, dict(
                    {key: field.value for key, field in fields.items()}, content_format='html', case_id=case.id))
            except (ValueError, ValidationError, TypeError):
                message.text = '상담 유형, 날짜·시각, 상담 시간(1~1440분)을 확인해 주세요. 입력 길이 제한도 확인해 주세요.'
                return
            self.editor_saving = True
            for field in (*fields.values(), save_button):
                field.disable()
            message.text = '저장 중입니다…'
            try:
                if entry is None:
                    entry = await run.io_bound(self.counseling.create, value)
                else:
                    entry = await run.io_bound(self.counseling.update, entry.id, value)
            except DatabaseError as error:
                message.text = str(error)
            else:
                self.editor_original = {key: field.value for key, field in fields.items()}
                message.text = '상담 일지를 저장했습니다.'
                ui.notify(f'{self.log_name}를 저장했습니다.', type='positive')
                self.log_offset = 0
                await self.load_logs()
                if self.on_saved:
                    await self.on_saved(student.id)
            finally:
                self.editor_saving = False
                for field in (*fields.values(), save_button):
                    field.enable()

        save_button.on_click(save)

    async def open_record(self, entry_id: int) -> None:
        """캘린더에서 전달받은 일지의 학생을 선택하고 기존 편집기를 연다."""
        if not await self.confirm_editor_discard():
            return
        self.clear_editor()
        self.student_request += 1
        self.log_request += 1
        request = self.student_request
        try:
            entry = await run.io_bound(self.counseling.get, entry_id)
            student = await run.io_bound(self.students.get, entry.student_id) if entry else None
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            return
        if request != self.student_request:
            return
        if entry is None or student is None:
            ui.notify('상담 일지 또는 학생이 존재하지 않습니다.', type='warning')
            return
        if self.on_selected:
            await self.on_selected(student.id)
            if request != self.student_request:
                return
        self.selected = student
        self.student_heading.text = f'{student.name} · {student.grade}학년 {student.classroom}반'
        self.add_case.enable()
        self.log_offset = 0
        await self.load_cases(preferred_id=entry.case_id)
        if request == self.student_request:
            await self.open_editor(entry_id)

    def build_editor(self, student: Student, entry: Counseling | None):
        """상담 입력 필드와 WYSIWYG 에디터를 구성한다."""
        initial = entry.model_dump() if entry else dict(title='', category='개인상담', status='scheduled',
            duration_minutes=50, content_markdown='', follow_up='', starts_at=datetime.now(KST).replace(second=0, microsecond=0))
        fields = {}
        local_start = initial['starts_at'].astimezone(KST)
        target = initial.get('counseling_target') or '학생본인'
        if target == '보호자':
            target = '보호자(가족)'
        previous_target = target
        if target not in TARGET_CATEGORIES:
            target = None
        with ui.column().classes('w-full min-w-0 gap-4') as panel:
            ui.label('상담 일지 수정' if entry else '새 상담 일지 작성').classes('text-2xl font-bold')
            ui.label(f'{student.name} · {student.grade}학년 {student.classroom}반 · 학번 {student.student_number or "미입력"}').classes('text-slate-500')
            with ui.row().classes('w-full items-start'):
                fields['starts_on'] = ui.date_input('상담 날짜', value=local_start.date().isoformat()).props('outlined').classes('grow')
                fields['starts_time'] = time_input('시작 시각 (한국 시각)', value=local_start.time().isoformat()).props('outlined').classes('grow')
                fields['duration_minutes'] = ui.number('상담 시간 (분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-36')
                fields['category'] = ui.input('상담 유형', value=TARGET_CATEGORIES.get(target, initial['category']))
                fields['category'].set_visibility(False)
                fields['status'] = ui.select(STATUSES, label='상담 상태', value=initial['status']).props('outlined').classes('w-36')
            with ui.row().classes('w-full items-start'):
                method = initial.get('counseling_method', '')
                methods = ['면담', '전화상담', '사이버상담']
                if method and method not in methods:
                    methods.append(method)
                fields['counseling_method'] = ui.select(
                    methods, label='상담 방법', value=method or None,
                ).props('outlined clearable').classes('grow')
                fields['counseling_target'] = ui.select(
                    list(TARGET_CATEGORIES), label='상담 대상', value=target,
                ).props('outlined').classes('grow')
                if target is None:
                    ui.label(f'기존 상담 대상: {previous_target}. 상담 대상을 다시 선택해 주세요.').classes('text-sm text-amber-700')
                areas = list(GUARDIAN_COUNSELING_AREAS if target == '보호자(가족)' else COUNSELING_AREAS)
                area = initial.get('counseling_area') or None
                if area and area not in areas:
                    if target == '보호자(가족)':
                        ui.label(f'기존 상담 분야: {area}. 보호자 상담 분야를 다시 선택하세요.').classes('text-sm text-amber-700')
                        area = None
                    else:
                        areas.append(area)
                fields['counseling_area'] = ui.select(
                    areas, label='상담 분야', value=area,
                ).props('outlined clearable').classes('grow')

                def update_areas(event):
                    if event.value in TARGET_CATEGORIES:
                        fields['category'].value = TARGET_CATEGORIES[event.value]
                    options = list(GUARDIAN_COUNSELING_AREAS if event.value == '보호자(가족)' else COUNSELING_AREAS)
                    selected = fields['counseling_area'].value
                    fields['counseling_area'].set_options(options, value=selected if selected in options else None)

                fields['counseling_target'].on_value_change(update_areas)
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-2 gap-4 items-start'):
                with ui.column().classes('w-full min-w-0 gap-3'):
                    ui.label('상담 내용').classes('font-semibold')
                    fields['content_markdown'] = ui.editor(
                        value=editor_html(initial['content_markdown'], initial.get('content_format', 'markdown')),
                        placeholder='상담 내용을 입력하세요.',
                    ).classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
                with ui.column().classes('w-full min-w-0 gap-3'):
                    ui.label('비밀 메모').classes('font-semibold')
                    fields['private_note_html'] = ui.editor(
                        value=clean_html(initial.get('private_note_html', '')),
                        placeholder='비밀 메모를 입력하세요.',
                    ).classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            fields['follow_up'] = ui.textarea('후속 조치', value=initial['follow_up']).props('outlined rows=2 maxlength=20000').classes('w-full')
            message = ui.label().classes('text-sm text-red-700')
            for field in fields.values():
                field.on_value_change(lambda: message.set_text(''))
            with ui.row().classes('w-full items-center'):
                attachment_button(self.counseling.database, 'counseling', entry.id if entry else None)
                ui.space()
                save = ui.button('일지 저장', icon='save')
        return panel, fields, message, save
