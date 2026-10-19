"""학생별 상담 일지 목록과 마크다운 편집/미리보기. SQL은 저장소에 위임한다."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from nicegui import run, ui
from pydantic import ValidationError

from database import DatabaseError
from models import Counseling, CounselingInput, Student
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from views.student_list import StudentList

KST = timezone(timedelta(hours=9))
PAGE_SIZE = 20
STATUSES = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}


def counseling_form_input(student_id: int, values: dict) -> CounselingInput:
    """화면의 한국 시각을 시간대가 포함된 모델로 바꾼다. 마크다운은 가공하지 않는다."""
    data = dict(values)
    starts_at = datetime.fromisoformat(data['starts_at'])
    if starts_at.tzinfo is not None:
        raise ValueError('상담 일시는 한국 시각으로 입력해 주세요.')
    data['starts_at'] = starts_at.replace(tzinfo=KST)
    return CounselingInput(student_id=student_id, **data)


class CounselingView:
    """페이지별 학생 선택과 조회 상태를 관리한다. 편집은 모달에서 격리한다."""

    def __init__(self, students: StudentRepository, counseling: CounselingRepository,
                 on_saved: Callable[[int], Awaitable[None]] | None = None):
        self.students = students
        self.counseling = counseling
        self.on_saved = on_saved
        self.selected: Student | None = None
        self.log_offset = 0
        self.student_request = 0
        self.log_request = 0
        self.editor_open = False

    def build(self) -> None:
        """학생 검색, 선택 학생의 상담 목록을 구성한다."""
        with ui.column().classes('w-full gap-5 p-4 md:p-8'):
            ui.label('상담 일지').classes('text-3xl font-bold text-slate-800')
            ui.label('학생을 선택하고 상담 내용을 기록하세요.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-start gap-6'):
                self.student_list = StudentList(self.students, on_select=self.select_student)
                self.student_list.build()
                with ui.card().classes('w-full min-w-0 rounded-2xl shadow-sm p-5'):
                    with ui.row().classes('w-full items-center justify-between'):
                        self.student_heading = ui.label('상담 대상 학생을 선택해 주세요.').classes('text-xl font-bold')
                        self.add = ui.button('새 상담 일지', icon='edit_note', on_click=lambda: self.open_editor())
                        self.add.disable()
                    self.logs = ui.column().classes('w-full gap-3')
                    self.log_message = ui.label().classes('text-sm text-slate-500')
                    with ui.row().classes('w-full items-center justify-end'):
                        self.log_previous = ui.button('일지 이전', on_click=lambda: self.log_page(-1)).props('flat')
                        self.log_page_label = ui.label()
                        self.log_next = ui.button('일지 다음', on_click=lambda: self.log_page(1)).props('flat')
                        ui.button('일지 새로고침', icon='refresh', on_click=self.load_logs).props('flat')
                    self.log_previous.disable()
                    self.log_next.disable()

    async def select_student(self, student_id: int | None) -> None:
        """상담 대상의 최신 프로필을 읽고 다른 학생의 이전 일지를 즉시 숨긴다."""
        self.student_request += 1
        self.log_request += 1
        request = self.log_request
        self.selected = None
        self.logs.clear()
        self.log_message.text = ''
        self.student_heading.text = '상담 대상 학생을 선택해 주세요.'
        self.add.disable()
        self.log_previous.disable()
        self.log_next.disable()
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
        self.add.enable()
        self.log_offset = 0
        await self.load_logs()

    async def log_page(self, direction: int) -> None:
        """선택 학생의 상담 목록 페이지를 이동한다."""
        self.log_offset = max(0, self.log_offset + direction * PAGE_SIZE)
        await self.load_logs()

    async def load_logs(self) -> None:
        """선택 학생의 상담 목록을 최신순으로 읽는다."""
        if self.selected is None:
            return
        self.log_request += 1
        request = self.log_request
        self.logs.clear()
        self.log_previous.disable()
        self.log_next.disable()
        self.log_message.text = '상담 일지를 불러오는 중입니다…'
        try:
            entries = await run.io_bound(self.counseling.list, student_id=self.selected.id,
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
                        ui.label(f'{entry.starts_at.astimezone(KST):%Y.%m.%d %H:%M} · {STATUSES[entry.status]} · {entry.category} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                    ui.button('열기 / 수정', icon='edit', on_click=lambda entry_id=entry.id: self.open_editor(entry_id)).props('outline')
        self.log_message.text = f'이 페이지에 {min(len(entries), PAGE_SIZE)}건 · 한국 표준시' if entries else '등록된 상담 일지가 없습니다. 새 상담 일지를 작성해 보세요.'
        self.log_page_label.text = f'{self.log_offset // PAGE_SIZE + 1} 페이지'
        self.log_previous.set_enabled(self.log_offset > 0)
        self.log_next.set_enabled(len(entries) > PAGE_SIZE)

    async def open_editor(self, entry_id: int | None = None) -> None:
        """원문을 유지하는 편집 모달. 실패 시 입력을 보존하며 미저장 취소를 확인한다."""
        if self.editor_open or self.selected is None:
            return
        self.editor_open = True
        student = self.selected
        dialog = None
        try:
            entry = None
            if entry_id is not None:
                try:
                    entry = await run.io_bound(self.counseling.get, entry_id)
                except DatabaseError as error:
                    ui.notify(str(error), type='negative')
                    return
                if entry is None or entry.student_id != student.id:
                    ui.notify('상담 일지를 찾을 수 없습니다. 목록을 새로고침해 주세요.', type='warning')
                    return
            # 모달을 목록 하위가 아닌 클라이언트 루트에 붙여 목록 재조회와 수명을 분리한다.
            with ui.context.client.content:
                dialog, fields, message, save_button, cancel_button = self.build_editor(student, entry)
            original = {key: field.value for key, field in fields.items()}
            saving = False

            async def cancel() -> None:
                if saving:
                    return
                if original != {key: field.value for key, field in fields.items()}:
                    with ui.dialog().props('persistent') as confirm, ui.card():
                        ui.label('저장하지 않은 내용을 버릴까요?')
                        with ui.row():
                            ui.button('계속 작성', on_click=lambda: confirm.submit(False)).props('flat')
                            ui.button('변경 내용 버리기', on_click=lambda: confirm.submit(True)).props('color=negative')
                    discard = await confirm
                    if not confirm.is_deleted:
                        confirm.delete()
                    if not discard:
                        return
                dialog.submit(False)

            async def save() -> None:
                nonlocal saving, entry
                if saving:
                    return
                try:
                    value = counseling_form_input(student.id, {key: field.value for key, field in fields.items()})
                except (ValueError, ValidationError, TypeError):
                    message.text = '제목·유형을 입력하고 일시와 상담 시간(1~1440분)을 확인해 주세요. 본문은 최대 200,000자입니다.'
                    return
                saving = True
                for field in fields.values():
                    field.disable()
                save_button.disable()
                cancel_button.disable()
                message.text = '저장 중입니다…'
                try:
                    if entry is None:
                        entry = await run.io_bound(self.counseling.create, value)
                    else:
                        entry = await run.io_bound(self.counseling.update, entry.id, value)
                except DatabaseError as error:
                    message.text = str(error)
                else:
                    dialog.submit(True)
                finally:
                    saving = False
                    for field in fields.values():
                        field.enable()
                    save_button.enable()
                    cancel_button.enable()

            save_button.on_click(save)
            cancel_button.on_click(cancel)
            saved = await dialog
            if saved:
                ui.notify('상담 일지를 저장했습니다.', type='positive')
                self.log_offset = 0
                await self.load_logs()
                if self.on_saved:
                    await self.on_saved(student.id)
        finally:
            self.editor_open = False
            if dialog is not None and not dialog.is_deleted:
                dialog.delete()

    async def open_record(self, entry_id: int) -> None:
        """캘린더에서 전달받은 일지의 학생을 선택하고 기존 편집기를 연다."""
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
        self.selected = student
        self.student_heading.text = f'{student.name} · {student.grade}학년 {student.classroom}반'
        self.add.enable()
        self.log_offset = 0
        await self.load_logs()
        if request == self.student_request:
            await self.open_editor(entry_id)

    def build_editor(self, student: Student, entry: Counseling | None):
        """편집 필드와 정화된 HTML 미리보기를 만든다. 저장 내용에는 렌더링 결과를 사용하지 않는다."""
        initial = entry.model_dump() if entry else dict(title='', category='개인상담', status='completed',
            duration_minutes=50, content_markdown='', follow_up='', starts_at=datetime.now(KST).replace(second=0, microsecond=0))
        fields = {}
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6 gap-4'):
            ui.label('상담 일지 수정' if entry else '새 상담 일지 작성').classes('text-2xl font-bold')
            ui.label(f'{student.name} · {student.grade}학년 {student.classroom}반 · 학번 {student.student_number or "미입력"}').classes('text-slate-500')
            fields['title'] = ui.input('상담 제목', value=initial['title']).props('outlined maxlength=200').classes('w-full')
            with ui.row().classes('w-full items-start'):
                fields['starts_at'] = ui.input('상담 일시 (한국 시각)', value=initial['starts_at'].astimezone(KST).replace(tzinfo=None).isoformat()).props('outlined type=datetime-local step=any').classes('grow')
                fields['duration_minutes'] = ui.number('상담 시간 (분)', value=initial['duration_minutes'], min=1, max=1440, step=1).props('outlined').classes('w-36')
                fields['category'] = ui.input('상담 유형', value=initial['category']).props('outlined maxlength=100').classes('grow')
                fields['status'] = ui.select(STATUSES, label='상담 상태', value=initial['status']).props('outlined').classes('w-36')
            with ui.row().classes('w-full items-stretch gap-4 flex-col md:flex-row'):
                with ui.column().classes('flex-1 min-w-0'):
                    ui.label('마크다운 편집').classes('font-semibold')
                    fields['content_markdown'] = ui.textarea('상담 내용', value=initial['content_markdown'],
                        placeholder='## 상담 내용\n\n- 학생이 이야기한 내용\n- 상담 중 관찰한 내용').props('outlined rows=14 maxlength=200000').classes('w-full')
                    ui.label('## 제목 · **강조** · - 목록').classes('text-sm text-slate-500')
                with ui.column().classes('flex-1 min-w-0 border rounded-xl p-4'):
                    ui.label('실시간 미리보기').classes('font-semibold')
                    preview = ui.markdown(initial['content_markdown'], sanitize=True).classes('w-full break-words overflow-auto')
                    fields['content_markdown'].on_value_change(lambda event: preview.set_content(event.value or ''))
            fields['follow_up'] = ui.textarea('후속 조치', value=initial['follow_up']).props('outlined rows=2 maxlength=20000').classes('w-full')
            message = ui.label().classes('text-sm text-red-700')
            for field in fields.values():
                field.on_value_change(lambda: message.set_text(''))
            with ui.row().classes('w-full justify-end'):
                cancel = ui.button('작성 닫기').props('flat')
                save = ui.button('일지 저장', icon='save')
        return dialog, fields, message, save, cancel
