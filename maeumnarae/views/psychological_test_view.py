"""왼쪽 학생 목록과 오른쪽 학생별 심리검사 일지 목록."""
from datetime import datetime

from maeumnarae.views.journal_pagination import PAGE_SIZE, load_page

from nicegui import run, ui
from maeumnarae.views.journal_print_view import list_print_tools, editor_print_button

from maeumnarae.views.attachment_view import attachment_button

from maeumnarae.views.delete_action import delete_button

from maeumnarae.views.time_inputs import storage_time, time_input

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import PsychologicalTestInput
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.views.counseling_view import KST
from maeumnarae.views.student_list import StudentList
from maeumnarae.views.counseling_content import clean_html, editor_html


TEST_NAMES = ['MMPI-A(다면적 인성검사-청소년용)', 'MMPI-2(다면적 인성검사)', 'JTCI(청소년용 기질 및 성격 검사)', 'TCI(기질 및 성격 검사)', 'MBTI', 'SCT(문장완성검사)', 'HTP(집나무사람 그림 검사)', 'KFD(동적가족화검사)', 'K-WISC-V(아동용 웩슬러 지능검사 5판)', 'K-WAIS-IV(성인용 웩슬러 지능검사 4판)', '진로흥미검사', '학습전략검사']


class PsychologicalTestView:
    def __init__(self, students):
        self.students = students
        self.repository = PsychologicalTestRepository(students.database)
        self.selected = None
        if hasattr(self, 'pdf_selection'):
            self.pdf_selection.set_scope(None)
        self.request = 0
        self.offset = 0
        self.editor_saving = False
        self.editor_request = 0
        self.editor_values = lambda: ()
        self.editor_original = ()
        self.editor_attachments = None

    @property
    def editor_open(self):
        return self.editor_saving or bool(self.editor_attachments and self.editor_attachments.pending) or self.editor_original != self.editor_values()

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
        self.editor_request += 1
        self.editor_values = lambda: ()
        self.editor_original = ()
        self.editor_attachments = None
        self.editor_container.clear()
        with self.editor_container:
            ui.label('새 심리검사 일지를 작성하거나 일지를 선택해 주세요.').classes('text-slate-500')

    def build(self, *, embedded=False):
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            if not embedded:
                ui.label('심리검사').classes('text-3xl font-bold text-slate-800')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6' if embedded else 'w-full grid grid-cols-1 lg:grid-cols-[2fr_3fr_5fr] items-start gap-6'):
                if not embedded:
                    self.student_list = StudentList(self.students, on_select=self.select_student)
                    self.student_list.build()
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    self.student_heading = ui.label('검사 대상 학생을 선택해 주세요.').classes('text-xl font-bold')
                    self.student_heading.set_visibility(not embedded)
                    if not embedded:
                        ui.separator()
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('심리검사 일지 목록').classes('text-lg font-bold')
                        self.add = ui.button('새 심리검사 일지', icon='edit_note', on_click=lambda: self.open_editor())
                        self.add.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.message = ui.label('학생 관리에서 상담 대상 학생을 선택해 주세요.').classes('text-sm text-slate-500')
                    with ui.row().classes('w-full items-center justify-end'):
                        self.previous = ui.button('일지 이전', on_click=lambda: self.change_page(-1)).props('flat')
                        self.page_label = ui.label()
                        self.next = ui.button('일지 다음', on_click=lambda: self.change_page(1)).props('flat')
                    self.previous.disable()
                    self.next.disable()

                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    self.editor_container = ui.column().classes('w-full min-w-0 gap-4')
                    self.clear_editor()

    async def select_student(self, student_id):
        if not await self.confirm_editor_discard():
            return
        self.clear_editor()
        self.request += 1
        request = self.request
        self.selected = None
        if hasattr(self, 'pdf_selection'):
            self.pdf_selection.set_scope(None)
        self.offset = 0
        self.add.disable()
        self.logs.clear()
        self.previous.disable()
        self.next.disable()
        self.page_label.text = ''
        self.student_heading.text = '검사 대상 학생을 선택해 주세요.'
        self.message.text = '학생 관리에서 상담 대상 학생을 선택해 주세요.'
        if student_id is None:
            return
        self.message.text = '학생 정보를 불러오는 중입니다…'
        try:
            student = await run.io_bound(self.students.get, student_id)
        except DatabaseError as error:
            if request == self.request:
                self.message.text = str(error)
            return
        if request != self.request:
            return
        if student is None:
            self.message.text = '학생이 존재하지 않습니다. 학생 목록을 새로고침해 주세요.'
            return
        self.selected = student
        self.student_heading.text = f'{student.name} · {student.grade}학년 {student.classroom}반'
        self.add.enable()
        await self.load_logs()

    async def change_page(self, direction):
        self.offset = max(0, self.offset + direction * PAGE_SIZE)
        await self.load_logs()

    async def after_log_deleted(self):
        self.clear_editor()
        self.offset = 0
        await self.load_logs()

    async def load_logs(self):
        if self.selected is None:
            return
        self.request += 1
        request = self.request
        self.logs.clear()
        self.previous.disable()
        self.next.disable()
        self.page_label.text = ''
        self.message.text = '심리검사 일지를 불러오는 중입니다…'
        try:
            entries, offset, pages = await run.io_bound(
                load_page, self.repository.list, self.repository.count, self.offset,
                self.selected.id)
        except DatabaseError as error:
            if request == self.request:
                self.message.text = str(error)
                self.previous.set_enabled(self.offset > 0)
            return
        if request != self.request:
            return
        self.offset = offset
        with self.logs:
            pdf = list_print_tools(self, self.repository.database, 'test', self.selected.id)
            for entry in entries[:PAGE_SIZE]:
                open_log = lambda entry=entry: self.open_editor(entry)
                with ui.row().classes(
                        'w-full items-center justify-between border rounded-xl p-4 cursor-pointer hover:bg-slate-50 focus-visible:outline'
                ).props('role=button tabindex=0 aria-label="일지 열기"').on('click', open_log).on(
                        'keydown.enter.self.prevent', open_log).on('keydown.space.self.prevent', open_log):
                    with ui.column().classes('gap-1 min-w-0 flex-1'):
                        ui.label(entry.title).classes('font-semibold break-words w-full')
                        details = [f'{entry.test_date:%Y.%m.%d}' + (f' {entry.test_time}' if entry.test_time else ''), entry.target]
                        if entry.duration_minutes is not None:
                            details.append(f'{entry.duration_minutes}분')
                        ui.label(' · '.join(details)).classes('text-sm text-slate-500')
                    pdf.row(entry.id)
                    delete_button(self.repository.database, 'test', lambda entry=entry: entry, self.after_log_deleted, blocked=lambda: self.editor_open, icon_only=True)

        self.message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건' if entries else '등록된 심리검사 일지가 없습니다.'
        self.page_label.text = f'{self.offset // PAGE_SIZE + 1}페이지/{pages}페이지'
        self.previous.set_enabled(self.offset > 0)
        self.next.set_enabled(self.offset // PAGE_SIZE + 1 < pages)

    async def open_editor(self, entry=None):
        if self.selected is None:
            return
        student = self.selected
        if entry is not None and entry.student_id != student.id:
            return
        if not await self.confirm_editor_discard():
            return
        self.clear_editor()
        request = self.editor_request
        with self.editor_container:
            ui.label('심리검사 일지 수정' if entry else '새 심리검사 일지').classes('text-2xl font-bold')
            ui.label(student.name).classes('text-slate-500')
            title_text = {'value': entry.title if entry else ''}
            title_options = list(TEST_NAMES)
            if entry and entry.title not in title_options:
                title_options.append(entry.title)
            title = ui.select(title_options, label='검사명 *', value=entry.title if entry else None,
                              with_input=True, new_value_mode='add-unique',
                              on_change=lambda event: title_text.update(value=event.value or '')).props(
                'outlined maxlength=200 placeholder="검사명의 일부를 입력하거나 직접 작성하세요"').classes('w-full')
            # Enter로 확정하지 않은 직접 입력도 저장 및 미저장 변경 감지에 포함한다.
            title.on('input-value', lambda event: title_text.update(value=event.args or ''))
            target = ui.select({'학생': '학생', '보호자(학부모)': '학부모'}, label='대상',
                               value=entry.target if entry else '학생').props('outlined').classes('w-full')
            with ui.row().classes('w-full items-start'):
                test_date = ui.date_input('검사일 *', value=(entry.test_date if entry else datetime.now(KST).date()).isoformat()).props('outlined').classes('grow min-w-40')
                test_time = time_input('시각', value=entry.test_time if entry else '09:00').props('outlined').classes('w-40')
                duration = ui.number('시간(분)', value=entry.duration_minutes if entry else 60,
                                     min=1, max=1440, step=1).props('outlined').classes('w-36')
            ui.label('검사 결과 및 소견').classes('font-semibold')
            content = ui.editor(value=editor_html(entry.content, entry.content_format) if entry else '',
                                placeholder='검사 결과 및 소견을 입력하세요.').classes('w-full').props("""min-height=320px :toolbar='[["bold", "italic", "underline", "strike"], ["unordered", "ordered"], ["left", "center", "right"], ["undo", "redo"]]'""")
            message = ui.label().classes('text-sm text-red-700')
            with ui.row().classes('w-full items-center'):
                files = attachment_button(self.repository.database, 'test', entry.id if entry else None)
                ui.space()
                save_button = ui.button('일지 저장', icon='save')
        fields = (title, target, test_date, test_time, duration, content)

        def current_values():
            return (title_text['value'], *(field.value for field in fields[1:]))

        self.editor_attachments = files
        self.editor_values = current_values
        self.editor_original = current_values()

        async def save():
            nonlocal entry
            if self.editor_saving or request != self.editor_request:
                return
            try:
                value = PsychologicalTestInput(student_id=student.id, title=title_text['value'],
                                               test_date=test_date.value, target=target.value, test_time=storage_time(test_time.value),
                                               duration_minutes=duration.value, content=clean_html(content.value or ''),
                                               content_format='html')
            except (ValueError, TypeError):
                message.text = '검사명(1~200자), 대상, 검사일, 시각(오전/오후 hh:mm), 시간(1~1440분 정수), 소견(최대 20,000자)을 확인해 주세요.'
                return
            self.editor_saving = True
            controls = (*fields, save_button)
            for control in controls:
                control.disable()
            try:
                entry = await files.save_record(self.repository.save, value, entry.id if entry else None)
            except DatabaseError as error:
                message.text = str(error)
            else:
                self.editor_original = current_values()
                message.text = '심리검사 일지를 저장했습니다.'
                ui.notify('심리검사 일지를 저장했습니다.', type='positive')
                self.offset = 0
                await self.load_logs()
            finally:
                self.editor_saving = False
                for control in controls:
                    control.enable()

        save_button.on_click(save)
        with save_button.parent_slot:
            editor_print_button(self.repository.database, 'test', lambda: entry, lambda: self.editor_open)
