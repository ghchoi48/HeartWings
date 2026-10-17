"""학생 목록, 편집 모달, 상세 프로필 및 상담 타임라인."""

from datetime import timedelta, timezone

from nicegui import events, run, ui
from pydantic import ValidationError

from database import DatabaseError
from models import Student, StudentInput
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository

KST = timezone(timedelta(hours=9))
PAGE_SIZE = 20
STATUS_LABELS = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}
FIELD_LABELS = {
    'name': '이름', 'student_number': '학번', 'grade': '학년',
    'classroom': '반', 'birth_date': '생년월일',
    'guardian_contact': '보호자 연락처', 'notes': '학생 메모', 'nickname': '별명',
}


def student_form_input(values: dict) -> StudentInput:
    """선택 항목의 빈 문자열을 정규화하고 모델에서 입력을 검증한다."""
    data = dict(values)
    for field in ('student_number', 'birth_date'):
        data[field] = data.get(field) or None
        if isinstance(data[field], str):
            data[field] = data[field].strip() or None
    return StudentInput(**data)


class StudentView:
    """클라이언트별 상태를 유지한다. DB 호출은 작업 스레드에서 수행한다."""

    def __init__(self, students: StudentRepository, counseling: CounselingRepository):
        self.students = students
        self.counseling = counseling
        self.offset = 0
        self.query = ''
        self.grade = None
        self.selected: Student | None = None
        self.list_request = 0
        self.detail_request = 0
        self.timeline_offset = 0
        self.timeline_busy = False
        self.timeline_more = False
        self.editor_open = False

    def build(self) -> None:
        """화면을 생성한다. 인스턴스 하나를 여러 클라이언트에서 공유하지 않는다."""
        with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8'):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.column().classes('gap-1'):
                    ui.label('학생 관리').classes('text-3xl font-bold text-slate-800')
                    ui.label('학생의 이야기를 차근차근 이어갑니다.').classes('text-slate-500')
                ui.button('학생 추가', icon='person_add', on_click=lambda: self.open_editor())
            with ui.card().classes('w-full rounded-2xl shadow-sm p-5'):
                with ui.row().classes('w-full items-end gap-3'):
                    self.search = ui.input('이름 또는 학번', placeholder='검색어를 입력하세요').props('outlined clearable').classes('grow')
                    self.search.on('keydown.enter', self.apply_filters)
                    self.grade_filter = ui.select(
                        {0: '전체 학년', **{i: f'{i}학년' for i in range(1, 13)}},
                        value=0, label='학년',
                    ).props('outlined').classes('w-36')
                    ui.button('검색', icon='search', on_click=self.apply_filters)
                    ui.button('초기화', on_click=self.reset_filters).props('flat')
                self.list_message = ui.label().classes('text-sm text-slate-500')
                columns = [
                    {'name': name, 'label': label, 'field': name, 'align': 'left'}
                    for name, label in [('name', '이름'), ('grade', '학년'),
                                        ('classroom', '반'), ('student_number', '학번')]
                ]
                self.table = ui.table(columns=columns, rows=[], row_key='id',
                                      pagination=0).classes('w-full').props('flat hide-bottom')
                self.table.on('rowClick', self.select_student,
                              js_handler='(event, row) => emit(row.id)')
                ui.label('학생 행을 클릭하면 아래에 상세 프로필과 상담 이력이 표시됩니다.').classes('text-sm text-slate-500')
                with ui.row().classes('w-full items-center justify-end'):
                    self.previous = ui.button('이전', on_click=lambda: self.change_page(-1)).props('flat')
                    self.page_label = ui.label()
                    self.next = ui.button('다음', on_click=lambda: self.change_page(1)).props('flat')
                self.previous.disable()
                self.next.disable()
            self.detail = ui.column().classes('w-full gap-4')
            self.show_empty_detail()
        ui.timer(0.01, self.load_students, once=True)

    def show_empty_detail(self) -> None:
        """선택이 없거나 조회 중일 때 이전 학생의 민감 정보를 화면에서 제거한다."""
        self.detail.clear()
        with self.detail:
            with ui.card().classes('w-full items-center p-8 rounded-2xl shadow-sm'):
                ui.icon('person_outline', size='36px').classes('text-slate-400')
                ui.label('목록에서 학생을 선택해 주세요.').classes('text-slate-500')

    async def apply_filters(self) -> None:
        """검색 조건을 적용하고 첫 페이지부터 조회한다."""
        self.query = (self.search.value or '').strip()
        self.grade = self.grade_filter.value or None
        self.offset = 0
        await self.load_students()

    async def reset_filters(self) -> None:
        """검색과 학년 선택을 초기화한다."""
        self.search.value = ''
        self.grade_filter.value = 0
        await self.apply_filters()

    async def change_page(self, direction: int) -> None:
        """서버 저장소의 페이지를 이동한다."""
        self.offset = max(0, self.offset + direction * PAGE_SIZE)
        await self.load_students()

    async def load_students(self) -> None:
        """한 개를 추가 조회해 다음 페이지 유무를 결정한다. 늦은 응답은 무시한다."""
        self.list_request += 1
        request = self.list_request
        self.detail_request += 1
        self.selected = None
        self.table.rows = []
        self.show_empty_detail()
        self.previous.disable()
        self.next.disable()
        self.list_message.text = '학생 목록을 불러오는 중입니다…'
        try:
            students = await run.io_bound(self.students.list, search=self.query, grade=self.grade,
                                          limit=PAGE_SIZE + 1, offset=self.offset)
        except DatabaseError as error:
            if request == self.list_request:
                self.list_message.text = str(error) + ' 검색을 눌러 다시 시도하세요.'
            return
        if request != self.list_request:
            return
        self.table.rows = [dict(id=s.id, name=s.name, grade=s.grade, classroom=s.classroom,
                                student_number=s.student_number or '—') for s in students[:PAGE_SIZE]]
        self.table.update()
        self.page_label.text = f'{self.offset // PAGE_SIZE + 1} 페이지'
        self.previous.set_enabled(self.offset > 0)
        self.next.set_enabled(len(students) > PAGE_SIZE)
        self.list_message.text = f'이 페이지에 {min(len(students), PAGE_SIZE)}명' if students else '검색 조건에 맞는 학생이 없습니다. 학생 추가 또는 검색 초기화를 이용하세요.'

    async def select_student(self, event: events.GenericEventArguments) -> None:
        """클릭한 행의 학생 프로필과 이력을 조회한다."""
        await self.load_profile(event.args)

    async def load_profile(self, student_id: int | None) -> None:
        """다른 학생의 지연 응답이 현재 선택을 덮어쓰지 않도록 요청 번호를 검사한다."""
        self.detail_request += 1
        request = self.detail_request
        self.selected = None
        self.show_empty_detail()
        if student_id is None:
            return
        try:
            student = await run.io_bound(self.students.get, student_id)
        except DatabaseError as error:
            if request == self.detail_request:
                ui.notify(str(error), type='negative')
            return
        if request != self.detail_request:
            return
        if student is None:
            ui.notify('학생이 삭제되었거나 존재하지 않습니다. 목록을 다시 검색해 주세요.', type='warning')
            return
        self.selected = student
        self.detail.clear()
        with self.detail:
            with ui.card().classes('w-full rounded-2xl shadow-sm p-6'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label(student.name).classes('text-2xl font-bold')
                    ui.button('학생 정보 수정', icon='edit', on_click=lambda: self.open_editor(student)).props('outline')
                ui.label(f'{student.grade}학년 {student.classroom}반 · 학번 {student.student_number or "미입력"}').classes('text-slate-500')
                ui.separator()
                ui.label(f'생년월일: {student.birth_date or "미입력"}')
                ui.label(f'보호자 연락처: {student.guardian_contact or "미입력"}')
                ui.label('학생 메모').classes('font-semibold mt-2')
                ui.label(student.notes or '등록된 메모가 없습니다.').classes('whitespace-pre-wrap break-words w-full')
            with ui.card().classes('w-full rounded-2xl shadow-sm p-6'):
                ui.label('상담 타임라인').classes('text-xl font-bold')
                ui.label('최신순 · 한국 표준시(KST) · 예약 및 취소 포함').classes('text-sm text-slate-500')
                self.timeline = ui.column().classes('w-full gap-3')
                self.timeline_message = ui.label().classes('text-sm text-slate-500')
                self.more = ui.button('이력 더 보기', on_click=self.load_timeline).props('flat')
        self.timeline_offset = 0
        self.timeline_busy = False
        self.timeline_more = True
        await self.load_timeline()

    async def load_timeline(self) -> None:
        """상담 이력을 페이지 단위로 추가한다. 원문은 실행되지 않는 텍스트로 표시한다."""
        if self.selected is None or self.timeline_busy or not self.timeline_more:
            return
        request, student_id = self.detail_request, self.selected.id
        self.timeline_busy = True
        self.more.disable()
        self.timeline_message.text = '상담 이력을 불러오는 중입니다…'
        try:
            entries = await run.io_bound(self.counseling.list, student_id=student_id,
                                         limit=PAGE_SIZE + 1, offset=self.timeline_offset)
            if request != self.detail_request:
                return
            with self.timeline:
                for entry in entries[:PAGE_SIZE]:
                    date_label = entry.starts_at.astimezone(KST).strftime('%Y.%m.%d %H:%M')
                    with ui.expansion(f'{date_label} · {entry.title}', icon='chat_bubble_outline').classes('w-full border rounded-lg'):
                        ui.label(f'{STATUS_LABELS[entry.status]} · {entry.category} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                        ui.label(entry.content_markdown or '작성된 상담 내용이 없습니다.').classes('whitespace-pre-wrap break-words w-full')
                        if entry.follow_up:
                            ui.label('후속 조치').classes('font-semibold mt-3')
                            ui.label(entry.follow_up).classes('whitespace-pre-wrap break-words w-full')
            self.timeline_offset += min(len(entries), PAGE_SIZE)
            self.timeline_more = len(entries) > PAGE_SIZE
            self.timeline_message.text = f'{self.timeline_offset}건 표시' if self.timeline_offset else '아직 등록된 상담 이력이 없습니다.'
            self.more.set_visibility(self.timeline_more)
        except DatabaseError as error:
            if request == self.detail_request:
                self.timeline_message.text = str(error)
                self.more.text = '다시 시도'
        finally:
            if request == self.detail_request:
                self.timeline_busy = False
                self.more.enable()

    async def open_editor(self, student: Student | None = None) -> None:
        """학생 추가/수정 공통 모달. 저장 실패 시 입력을 유지하며 중복 저장을 막는다."""
        if self.editor_open:
            return
        self.editor_open = True
        initial = student.model_dump() if student else {}
        fields = {}
        saving = False
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-2xl p-6'):
            ui.label('학생 정보 수정' if student else '새 학생 등록').classes('text-2xl font-bold')
            ui.label('이름, 학년, 반은 필수 항목입니다.').classes('text-sm text-slate-500')
            with ui.column().classes('w-full gap-3'):
                with ui.row().classes('w-full'):
                    fields['name'] = ui.input('*이름', value=initial.get('name') or '').props('outlined').classes('grow')
                    fields['nickname'] = ui.input('별명', value=initial.get('nickname') or '').props('outlined').classes('grow')
                with ui.row().classes('w-full'):
                    fields['grade'] = ui.select({i: f'{i}학년' for i in range(1, 4)}, label='*학년', value=initial.get('grade', 1)).props('outlined').classes('grow')
                    fields['classroom'] = ui.input('*반', value=initial.get('classroom', '')).props('outlined').classes('grow')
                    fields['student_number'] = ui.input('학번', value=initial.get('student_number') or '').props('outlined').classes('grow')
                with ui.row().classes('w-full flex-nowrap items-start'):
                    fields['birth_date'] = ui.date_input('생년월일', value=str(initial.get('birth_date') or '')).props('outlined').classes('flex-1 min-w-0')
                    fields['student_contact'] = ui.input('학생 연락처', value=initial.get('student_contact', '')).props('outlined mask="###-####-####" inputmode="numeric"').classes('flex-1 min-w-0')
                    fields['guardian_contact'] = ui.input('보호자 연락처', value=initial.get('guardian_contact', '')).props('outlined mask="###-####-####" inputmode="numeric"').classes('flex-1 min-w-0')
                fields['notes'] = ui.textarea('학생 메모', value=initial.get('notes', '')).props('outlined').classes('w-full')
            error_label = ui.label().classes('text-red-700 text-sm whitespace-pre-wrap')

            async def save() -> None:
                nonlocal saving
                if saving:
                    return
                try:
                    value = student_form_input({key: element.value for key, element in fields.items()})
                except ValidationError as error:
                    invalid = list(dict.fromkeys(FIELD_LABELS.get(str(e['loc'][0]), '입력값') for e in error.errors()))
                    error_label.text = ', '.join(invalid) + ': 입력 형식과 길이를 확인하세요. 생년월일은 YYYY-MM-DD 형식입니다.'
                    return
                saving = True
                save_button.disable()
                cancel.disable()
                error_label.text = '저장 중입니다…'
                try:
                    if student:
                        saved = await run.io_bound(self.students.update, student.id, value)
                    else:
                        saved = await run.io_bound(self.students.create, value)
                except DatabaseError as error:
                    error_label.text = str(error)
                else:
                    dialog.submit(saved)
                finally:
                    saving = False
                    save_button.enable()
                    cancel.enable()

            with ui.row().classes('w-full justify-end'):
                cancel = ui.button('취소', on_click=lambda: dialog.submit(None)).props('flat')
                save_button = ui.button('저장', icon='save', on_click=save)
        try:
            saved = await dialog
            if saved is not None:
                ui.notify('학생 정보를 저장했습니다.', type='positive')
                await self.load_students()
                self.table.selected = [row for row in self.table.rows if row['id'] == saved.id]
                await self.load_profile(saved.id)
        finally:
            self.editor_open = False
            # 수정 후 프로필을 다시 그리면 그 안에서 열린 모달도 이미 제거될 수 있다.
            if not dialog.is_deleted:
                dialog.delete()
