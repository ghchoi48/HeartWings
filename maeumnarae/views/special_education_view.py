"""개인 상담과 같은 학생 선택/일지 흐름을 사용하는 특별교육 화면."""

from datetime import datetime

from maeumnarae.views.journal_pagination import PAGE_SIZE, load_page

from nicegui import run, ui
from maeumnarae.views.journal_print_view import list_print_tools

from maeumnarae.views.attachment_view import attachment_button

from maeumnarae.views.delete_action import delete_button

from maeumnarae.views.time_inputs import time_input

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import Counseling, Student, SpecialEducation, SpecialEducationInput
from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.views.counseling_view import CounselingView, KST, STATUSES, TARGET_LABELS, normalize_target, counseling_form_input
from maeumnarae.views.counseling_content import editor_html
from maeumnarae.views.student_list import StudentList


class SpecialEducationView(CounselingView):
    log_name = '특별 교육 일지'

    def __init__(self, students, on_saved=None):
        super().__init__(students, SpecialEducationLogRepository(students.database), on_saved)
        self.cases = SpecialEducationRepository(students.database)

    @property
    def editor_open(self) -> bool:
        return self.report_open

    @editor_open.setter
    def editor_open(self, value: bool) -> None:
        self.report_open = value

    async def confirm_editor_discard(self) -> bool:
        # 팝업을 닫기 전에는 선택 학생/교육을 바꾸지 않는다.
        return not self.editor_open

    def clear_editor(self) -> None:
        """특별교육은 팝업 편집기를 사용하므로 인라인 편집 영역이 없다."""
        self.editor_request += 1
        self.editor_fields = {}
        self.editor_original = {}

    async def select_case(self, case: SpecialEducation) -> None:
        if self.editor_open or self.selected is None or case.student_id != self.selected.id:
            return
        self.selected_case = case
        if case.id in self.case_options:
            self.case_select.set_value(case.id)
        self.set_case_actions_enabled(True)
        self.log_offset = 0
        self.add.enable()
        await self.load_logs()

    async def open_editor(self, entry_id: int | None = None) -> None:
        """선택한 특별교육의 일지를 팝업에서 작성하거나 수정한다."""
        if self.editor_open or self.selected is None or self.selected_case is None:
            return
        self.editor_open = True
        student, case = self.selected, self.selected_case
        dialog = None
        saving = False
        try:
            entry = await run.io_bound(self.counseling.get, entry_id) if entry_id is not None else None
            if entry_id is not None and (entry is None or entry.student_id != student.id or entry.case_id != case.id):
                ui.notify('특별 교육 일지를 찾을 수 없습니다. 목록을 새로고침해 주세요.', type='warning')
                return
            with ui.context.client.content:
                dialog, fields, message, save_button, cancel_button = self.build_editor(student, entry)
            original = {key: field.value for key, field in fields.items()}

            async def cancel():
                if saving:
                    return
                if save_button.attachments.pending or original != {key: field.value for key, field in fields.items()}:
                    with ui.dialog().props('persistent') as confirm, ui.card():
                        ui.label('저장하지 않은 내용을 버릴까요?')
                        ui.button('계속 작성', on_click=lambda: confirm.submit(False))
                        ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True))
                    try:
                        if not await confirm:
                            return
                    finally:
                        if not confirm.is_deleted:
                            confirm.delete()
                dialog.submit(False)

            async def save():
                nonlocal saving
                if saving:
                    return
                try:
                    value = counseling_form_input(student.id, dict(
                        {key: field.value for key, field in fields.items()}, content_format='html', case_id=case.id))
                except (ValueError, TypeError):
                    message.text = '교육 날짜·시간, 교육 시간(1~1440분)과 입력 길이를 확인해 주세요.'
                    return
                saving = True
                for field in (*fields.values(), save_button, cancel_button):
                    field.disable()
                try:
                    if entry is None:
                        await save_button.attachments.save_record(self.counseling.create, value)
                    else:
                        await save_button.attachments.save_record(self.counseling.update, entry.id, value)
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
                self.log_offset = 0
                await self.load_logs()
                if self.on_saved:
                    await self.on_saved(student.id)
                ui.notify('특별 교육 일지를 저장했습니다.', type='positive')
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    def set_case_actions_enabled(self, enabled: bool) -> None:
        self.edit_case.set_enabled(enabled)

    def build(self) -> None:
        """학생 검색, 선택 학생의 상담 목록을 구성한다."""
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('특별교육').classes('text-3xl font-bold text-slate-800')
            ui.label('학생을 선택하고 교육 내용을 기록하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                self.student_list = StudentList(self.students, on_select=self.select_student)
                self.student_list.build()
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        self.student_heading = ui.label('교육 대상 학생을 선택해 주세요.').classes('text-xl font-bold')
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('특별 교육 목록').classes('text-lg font-bold')
                        self.add_case = ui.button('새 특별 교육', icon='create_new_folder',
                                                  on_click=lambda: self.open_case_editor())
                        self.add_case.disable()
                    with ui.row().classes('w-full items-center'):
                        self.case_select = ui.select({}, label='특별 교육', on_change=self.change_case).props('outlined dense').classes('grow min-w-0')
                        self.case_select.disable()
                        delete_button(self.students.database, 'special', lambda: self.selected_case, self.after_case_deleted, blocked=lambda: self.editor_open)
                        self.edit_case = ui.button('특별 교육 정보 수정', icon='edit',
                                                   on_click=lambda: self.open_case_editor(self.selected_case)).props('outline')
                        self.edit_case.disable()
                    self.case_message = ui.label().classes('text-sm text-slate-500')
                    ui.separator()
                    with ui.row().classes('w-full items-center justify-between'):
                        self.log_heading = ui.label('특별 교육 일지 목록').classes('text-lg font-bold')
                        self.add = ui.button('새 특별 교육 일지', icon='edit_note', on_click=lambda: self.open_editor())
                        self.add.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.log_message = ui.label().classes('text-sm text-slate-500')
                    with ui.row().classes('w-full items-center justify-end'):
                        self.log_previous = ui.button('일지 이전', on_click=lambda: self.log_page(-1)).props('flat')
                        self.log_page_label = ui.label()
                        self.log_next = ui.button('일지 다음', on_click=lambda: self.log_page(1)).props('flat')
                    self.log_previous.disable()
                    self.log_next.disable()

    async def load_cases(self, preferred_id: int | None = None) -> None:
        if self.selected is None:
            return
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
        self.case_message.text = '특별 교육을 불러오는 중입니다…'
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
        self.case_message.text = f'{len(cases)}개 특별 교육 · 특별 교육을 선택해 특별 교육 일지를 확인하세요.' if cases else '등록된 특별 교육이 없습니다. 새 특별 교육을 만들어 주세요.'
        if cases:
            await self.select_case(next((case for case in cases if case.id == previous_id), cases[0]))

    async def open_case_editor(self, case: SpecialEducation | None = None) -> None:
        if self.editor_open or self.selected is None:
            return
        if case is not None and case.student_id != self.selected.id:
            return
        self.editor_open = True
        student = self.selected
        dialog = None
        try:
            with ui.context.client.content:
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6 gap-4'):
                    ui.label('특별 교육 정보 수정' if case else '새 특별 교육').classes('text-2xl font-bold')
                    ui.label(student.name).classes('text-slate-500')
                    with ui.row().classes('w-full flex-nowrap items-start gap-4'):
                        title = ui.input('특별교육명', value=case.title if case else '').props('outlined maxlength=200').classes('flex-1 min-w-0')
                        law = ui.select(['학교폭력예방법', '교원지위법'], label='관련 법령',
                                        value=case.law if case else None).props('outlined').classes('flex-1 min-w-0')
                        case_number = ui.input('사례번호', value=case.case_number if case else '').props('outlined maxlength=100').classes('flex-1 min-w-0')
                    message = ui.label().classes('text-sm text-red-700')
                    with ui.row().classes('w-full justify-end'):
                        cancel_button = ui.button('취소').props('flat')
                        save_button = ui.button('특별 교육 저장', icon='save')
            original = (title.value, law.value, case_number.value)
            saving = False

            async def cancel():
                if saving:
                    return
                if (title.value, law.value, case_number.value) != original:
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
                    value = SpecialEducationInput(student_id=student.id, title=title.value,
                                                law=law.value, case_number=case_number.value)
                except (ValueError, TypeError):
                    message.text = '특별교육명(1~200자), 관련 법령, 사례번호(최대 100자)를 확인해 주세요.'
                    return
                saving = True
                for field in (title, law, case_number, save_button, cancel_button):
                    field.disable()
                try:
                    saved = await run.io_bound(self.cases.save, value, case.id if case else None)
                    dialog.submit(saved)
                except DatabaseError as error:
                    message.text = str(error)
                finally:
                    saving = False
                    for field in (title, law, case_number, save_button, cancel_button):
                        field.enable()

            cancel_button.on_click(cancel)
            save_button.on_click(save)
            saved = await dialog
            self.editor_open = False
            if saved:
                ui.notify('특별 교육 정보를 저장했습니다.', type='positive')
                if self.selected and self.selected.id == student.id:
                    await self.load_cases(preferred_id=saved.id)
                if self.on_saved:
                    await self.on_saved(student.id)
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def load_logs(self) -> None:
        """선택 학생의 상담 목록을 최신순으로 읽는다."""
        if self.selected is None or self.selected_case is None:
            return
        self.log_request += 1
        request = self.log_request
        self.logs.clear()
        self.log_previous.disable()
        self.log_next.disable()
        self.log_message.text = '특별 교육 일지를 불러오는 중입니다…'
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
            pdf = list_print_tools(self, self.students.database, 'special', (self.selected.id, self.selected_case.id))
            for entry in entries[:PAGE_SIZE]:
                open_log = lambda entry_id=entry.id: self.open_editor(entry_id)
                with ui.row().classes(
                        'w-full items-center justify-between border rounded-xl p-4 cursor-pointer hover:bg-slate-50 focus-visible:outline'
                ).props('role=button tabindex=0 aria-label="일지 열기"').on('click', open_log).on(
                        'keydown.enter.self.prevent', open_log).on('keydown.space.self.prevent', open_log):
                    with ui.column().classes('gap-1'):
                        ui.label(self.selected_case.title).classes('font-semibold')
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {STATUSES[entry.status]} · {entry.category} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    with ui.row().classes('items-center gap-2 flex-nowrap shrink-0'):
                        pdf.row(entry.id)
                        delete_button(self.students.database, 'special_log', lambda entry=entry: entry, self.after_log_deleted, blocked=lambda: self.editor_open, icon_only=True)

        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 특별 교육 일지가 없습니다. 새 특별 교육 일지를 작성해 보세요.'
        self.log_page_label.text = f'{self.log_offset // PAGE_SIZE + 1}페이지/{pages}페이지'
        self.log_previous.set_enabled(self.log_offset > 0)
        self.log_next.set_enabled(self.log_offset // PAGE_SIZE + 1 < pages)

    def build_editor(self, student: Student, entry: Counseling | None):
        """상담 입력 필드와 WYSIWYG 에디터를 구성한다."""
        initial = entry.model_dump() if entry else dict(title='', category='특별교육', status='scheduled',
            duration_minutes=50, content_markdown='', follow_up='', starts_at=datetime.now(KST).replace(second=0, microsecond=0))
        fields = {}
        local_start = initial['starts_at'].astimezone(KST)
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6 gap-4'):
            ui.label('특별 교육 일지 수정' if entry else '새 특별 교육 일지 작성').classes('text-2xl font-bold')
            ui.label(f'{student.name} · {student.grade}학년 {student.classroom}반 · 학번 {student.student_number or "미입력"}').classes('text-slate-500')
            # 공용 일지 저장 흐름에 전달할 유형은 화면에서 편집하지 않는다.
            fields['category'] = ui.input(value=initial['category'])
            fields['category'].set_visibility(False)
            with ui.grid(columns=5).classes('w-full gap-4 items-start'):
                fields['starts_on'] = ui.date_input('교육 날짜', value=local_start.date().isoformat()).props('outlined').classes('w-full min-w-0')
                fields['starts_time'] = time_input('시간', value=local_start.time().isoformat()).props('outlined').classes('w-full min-w-0')
                fields['duration_minutes'] = ui.number('교육 시간 (분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-full min-w-0')
                target = normalize_target(initial.get('counseling_target', ''))
                fields['counseling_target'] = ui.select(
                    TARGET_LABELS, label='교육 대상', value=target if target in TARGET_LABELS else None,
                ).props('outlined clearable').classes('w-full min-w-0')
                fields['status'] = ui.select(STATUSES, label='교육 상태', value=initial['status']).props('outlined').classes('w-full min-w-0')
            if target and target not in TARGET_LABELS:
                ui.label(f'기존 교육 대상: {target}. 교육 대상을 다시 선택해 주세요.').classes('text-sm text-amber-700')
            with ui.column().classes('w-full gap-3'):
                ui.label('교육 내용').classes('font-semibold')
                fields['content_markdown'] = ui.editor(
                    value=editor_html(initial['content_markdown'], initial.get('content_format', 'markdown')),
                    placeholder='교육 내용을 입력하세요.',
                ).classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            fields['follow_up'] = ui.textarea('후속 조치', value=initial['follow_up']).props('outlined rows=2 maxlength=20000').classes('w-full')
            message = ui.label().classes('text-sm text-red-700')
            for field in fields.values():
                field.on_value_change(lambda: message.set_text(''))
            with ui.row().classes('w-full items-center'):
                files = attachment_button(self.counseling.database, 'special_log', entry.id if entry else None)
                ui.space()
                cancel = ui.button('취소').props('flat')
                save = ui.button('일지 저장', icon='save')
                save.attachments = files
        return dialog, fields, message, save, cancel
