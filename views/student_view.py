"""학생 목록, 편집 모달, 상세 프로필 및 상담 타임라인."""

from collections.abc import Awaitable, Callable
from datetime import timedelta, timezone

from nicegui import run, ui
from pydantic import ValidationError

from database import DatabaseError
from models import FamilyInput, FamilyMember, SchoolSettings, Student, StudentInput, current_school_year
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from repositories.school_settings_repo import SchoolSettingsRepository
from views.student_list import StudentList

KST = timezone(timedelta(hours=9))
PAGE_SIZE = 10
STATUS_LABELS = {'scheduled': '예약', 'completed': '완료', 'cancelled': '취소'}
FIELD_LABELS = {
    'school_year': '학년도', 'gender': '성별',
    'name': '이름', 'student_number': '번호', 'grade': '학년', 'classroom': '반', 'birth_date': '생년월일', 'student_contact': '학생 연락처', 'guardian_contact': '보호자 연락처', 'notes': '학생 메모', 'nickname': '별명',
}


def student_form_input(values: dict) -> StudentInput:
    """선택 항목의 빈 문자열을 정규화하고 모델에서 입력을 검증한다."""
    data = dict(values)
    for field in ('student_number', 'birth_date', 'gender'):
        data[field] = data.get(field) or None
        if isinstance(data[field], str):
            data[field] = data[field].strip() or None
    return StudentInput(**data)


class StudentView:
    """클라이언트별 상태를 유지한다. DB 호출은 작업 스레드에서 수행한다."""

    def __init__(self, students: StudentRepository, counseling: CounselingRepository,
                 school: SchoolSettingsRepository | None = None,
                 on_counseling: Callable[[int], Awaitable[None]] | None = None):
        self.students = students
        self.counseling = counseling
        self.school = school
        self.on_counseling = on_counseling
        self.selected: Student | None = None
        self.detail_request = 0
        self.timeline_offset = 0
        self.timeline_busy = False
        self.timeline_more = False
        self.editor_open = False

    def build(self) -> None:
        """화면을 생성한다. 인스턴스 하나를 여러 클라이언트에서 공유하지 않는다."""
        with ui.column().classes('w-full gap-6 p-4 md:p-8'):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.column().classes('gap-1'):
                    ui.label('학생 관리').classes('text-3xl font-bold text-slate-800')
                    ui.label('학생의 이야기를 차근차근 이어갑니다.').classes('text-slate-500')
            with ui.element('div').classes('w-full grid grid-cols-1 lg:grid-cols-[3fr_7fr] items-stretch gap-6'):
                self.student_list = StudentList(self.students, on_select=self.load_profile, page_size=PAGE_SIZE)
                self.student_list.build(autoload=False, on_add=lambda: self.open_editor())
                self.detail = ui.column().classes('w-full min-w-0 gap-4')
                self.show_empty_detail()
        ui.timer(0.01, self.load_students, once=True)

    def show_empty_detail(self) -> None:
        """선택이 없거나 조회 중일 때 이전 학생의 민감 정보를 화면에서 제거한다."""
        self.detail.clear()
        with self.detail:
            with ui.card().classes('w-full items-center p-8 rounded-2xl shadow-sm'):
                ui.icon('person_outline', size='36px').classes('text-slate-400')
                ui.label('목록에서 학생을 선택해 주세요.').classes('text-slate-500')

    async def load_students(self) -> None:
        """상세 표시를 초기화하고 학생 목록을 다시 조회한다."""
        self.detail_request += 1
        self.selected = None
        self.show_empty_detail()
        await self.student_list.reload()

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
            enrollments = await run.io_bound(self.students.enrollments, student_id) if student else []
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
            with ui.element('div').classes('w-full grid grid-cols-1 xl:grid-cols-2 items-start gap-4'):
                with ui.column().classes('w-full min-w-0 gap-4'):
                    with ui.card().classes('w-full rounded-2xl shadow-sm p-6'):
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label(student.name).classes('text-2xl font-bold')
                            ui.button('학생 정보 수정', icon='edit', on_click=lambda: self.open_editor(student)).props('outline')
                        ui.label(f'{student.school_year}학년도 · {student.grade}학년 {student.classroom}반 · 번호 {student.student_number or "미입력"}').classes('text-slate-500')
                        with ui.expansion('학년도별 학적 이력', icon='history').classes('w-full'):
                            for enrollment in enrollments:
                                with ui.row().classes('w-full items-center flex-nowrap gap-2 border-b border-slate-100 py-2'):
                                    with ui.column().classes('flex-1 min-w-0 gap-1'):
                                        ui.label(f'{enrollment.school_year}학년도').classes('font-semibold')
                                        ui.label(f'{enrollment.grade}학년 {enrollment.classroom}반 · 번호 {enrollment.student_number or "미입력"}').classes('text-sm text-slate-500 break-words')
                                    delete = ui.button(icon='delete_outline',
                                        on_click=lambda year=enrollment.school_year: self.delete_enrollment(student.id, year)).props(
                                            f'flat round color=negative aria-label="{enrollment.school_year}학년도 학적 이력 삭제"')
                                    delete.set_enabled(len(enrollments) > 1)
                                    delete.tooltip('학적 이력 삭제' if len(enrollments) > 1 else '마지막 학적 이력은 삭제할 수 없습니다.')
                        ui.separator()
                        ui.label(f'생년월일: {student.birth_date or "미입력"}')
                        ui.label(f'학생 연락처: {student.student_contact or "미입력"}')
                        ui.label('학생 메모').classes('font-semibold mt-2')
                        ui.label(student.notes or '등록된 메모가 없습니다.').classes('whitespace-pre-wrap break-words w-full')
                        ui.separator()
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label('가족 정보').classes('text-xl font-bold')
                            ui.button('가족 정보 수정', icon='edit', on_click=lambda: self.open_family_editor(student)).props('outline')
                        ui.label(f'가족 유형: {student.family_type or "미입력"}').classes('break-words w-full')
                        ui.label(f'가족 복지 유형: {student.family_welfare_type or "미입력"}').classes('break-words w-full')
                        ui.label('가족 구성원').classes('font-semibold')
                        if student.family_members:
                            ui.table(columns=[
                                {'name': key, 'label': label, 'field': key, 'align': 'left'}
                                for key, label in [('lives_together', '동거'), ('relationship', '관계'),
                                                   ('name', '이름'), ('age', '나이'),
                                                   ('occupation', '직업'), ('contact', '연락처')]
                            ], rows=[dict(member.model_dump(), id=index,
                                          lives_together='동거' if member.lives_together else '비동거',
                                          age=member.age if member.age is not None else '미입력')
                                     for index, member in enumerate(student.family_members)],
                                     row_key='id').classes('w-full').props('flat dense')
                        else:
                            ui.label('등록된 가족 구성원이 없습니다. 가족 정보 수정에서 구성원을 추가해 주세요.').classes('text-slate-500')
                with ui.card().classes('w-full rounded-2xl shadow-sm p-6'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label('상담 타임라인').classes('text-xl font-bold')
                        if self.on_counseling:
                            ui.button('상담 일지', icon='edit_note',
                                      on_click=lambda: self.on_counseling(student.id))
                    self.timeline = ui.timeline(side='right', layout='dense', color='primary').classes('w-full')
                    self.timeline_message = ui.label().classes('text-sm text-slate-500')
                    self.more = ui.button('이력 더 보기', on_click=self.load_timeline).props('flat')
        self.timeline_offset = 0
        self.timeline_busy = False
        self.timeline_more = True
        await self.load_timeline()

    async def delete_enrollment(self, student_id: int, school_year: int) -> None:
        """학적 삭제 중 중복 실행을 막고 학생 목록과 현재 프로필을 갱신한다."""
        if self.editor_open or self.selected is None or self.selected.id != student_id:
            return
        self.editor_open = True
        request = self.detail_request
        try:
            await run.io_bound(self.students.delete_enrollment, student_id, school_year)
            ui.notify(f'{school_year}학년도 학적 이력을 삭제했습니다.', type='positive')
            await self.student_list.reload()
            if request == self.detail_request and self.selected is not None and self.selected.id == student_id:
                await self.load_profile(student_id)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            self.editor_open = False

    async def load_timeline(self) -> None:
        """상담 이력을 페이지 단위로 추가하고 요약 항목만 표시한다."""
        if self.selected is None or self.timeline_busy or not self.timeline_more:
            return
        request, student_id = self.detail_request, self.selected.id
        self.timeline_busy = True
        self.more.disable()
        self.timeline_message.text = '상담 이력을 불러오는 중입니다…'
        try:
            entries = await run.io_bound(self.counseling.list_timeline, student_id=student_id,
                                         limit=PAGE_SIZE + 1, offset=self.timeline_offset)
            if request != self.detail_request:
                return
            with self.timeline:
                for entry in entries[:PAGE_SIZE]:
                    date_label = entry.starts_at.astimezone(KST).strftime('%Y.%m.%d %H:%M')
                    with ui.timeline_entry(title=date_label,
                                           icon={'group': 'groups', 'special_education': 'menu_book'}.get(entry.kind, 'chat_bubble_outline')):
                        if entry.kind == 'group':
                            ui.label(f'집단상담 · {entry.group_name} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                            ui.label(entry.title).classes('text-sm text-slate-500')
                        elif entry.kind == 'special_education':
                            ui.label(f'특별교육 · {entry.education_name} · {entry.duration_minutes}분').classes('text-sm text-slate-500')
                            ui.label(f'교육 대상: {entry.counseling_target or "미입력"}').classes('text-sm text-slate-500')
                        else:
                            ui.label(
                                f'{entry.counseling_area or "미지정"} · {entry.category} · {entry.duration_minutes}분'
                            ).classes('text-sm text-slate-500')
                            ui.label(
                                f'{entry.counseling_method or "미입력"} · {entry.counseling_target or "미입력"}'
                            ).classes('text-sm text-slate-500')
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

    async def open_family_editor(self, student: Student) -> None:
        """가족 정보 전용 모달. 실패 시 입력을 보존하고 재시도를 허용한다."""
        if self.editor_open:
            return
        self.editor_open = True
        saving = False
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-6xl p-6'):
            ui.label('가족 정보 수정').classes('text-2xl font-bold')
            with ui.row().classes('w-full'):
                family_options = ['양부모 가정', '한부모 가정', '조손 가정', '재혼 가정', '다문화 가정', '위탁 가정', '기타']
                welfare_options = ['해당 없음', '기초생활수급', '차상위계층', '한부모가족 지원', '기타']
                if student.family_type and student.family_type not in family_options:
                    family_options.append(student.family_type)
                if student.family_welfare_type and student.family_welfare_type not in welfare_options:
                    welfare_options.append(student.family_welfare_type)
                family_type = ui.select(family_options, label='가족 유형',
                                        value=student.family_type or None).props('outlined clearable').classes('grow')
                welfare_type = ui.select(welfare_options, label='가족 복지 유형',
                                         value=student.family_welfare_type or None).props('outlined clearable').classes('grow')
            ui.label('가족 구성원 목록').classes('text-lg font-semibold')
            member_rows = []
            empty_members_message = ui.label(
                '등록된 가족 구성원이 없습니다. 아래 구성원 추가 버튼을 눌러 가족 정보를 입력해 주세요.'
            ).classes('text-sm text-slate-500')
            with ui.element('div').classes('w-full overflow-x-auto'):
                members_container = ui.column().classes('w-full min-w-[850px] gap-2')

            def add_member(member: FamilyMember | None = None) -> None:
                if saving:
                    return
                member = member or FamilyMember()
                with members_container:
                    row = ui.element('div').classes(
                        'w-full grid grid-cols-[90px_1fr_1fr_80px_1fr_1.5fr_48px] items-center gap-2')
                    with row:
                        fields = {
                            'lives_together': ui.checkbox('동거', value=member.lives_together),
                            'relationship': ui.input('관계', value=member.relationship).props('outlined dense maxlength=100'),
                            'name': ui.input('이름', value=member.name).props('outlined dense maxlength=100'),
                            'age': ui.number('나이', value=member.age, min=0, max=150, step=1).props('outlined dense'),
                            'occupation': ui.input('직업', value=member.occupation).props('outlined dense maxlength=200'),
                            'contact': ui.input('연락처', value=member.contact).props(
                                'outlined dense mask="###-####-####" inputmode="numeric" type=tel'),
                        }
                        for field in fields.values():
                            field.classes('w-full min-w-0')

                        def remove_member() -> None:
                            if not saving:
                                member_rows.remove(fields)
                                row.delete()
                                empty_members_message.set_visibility(not member_rows)

                        ui.button(icon='delete_outline', on_click=remove_member).props(
                            'flat round color=negative aria-label="가족 구성원 삭제"').tooltip('구성원 삭제')
                member_rows.append(fields)
                empty_members_message.set_visibility(False)

            for member in student.family_members:
                add_member(member)
            ui.button('구성원 추가', icon='person_add', on_click=lambda: add_member()).props('outline')
            error_label = ui.label().classes('text-red-700 text-sm whitespace-pre-wrap')

            async def save() -> None:
                nonlocal saving
                if saving:
                    return
                try:
                    family = FamilyInput(
                        guardian_contact=student.guardian_contact,
                        family_type=family_type.value or '',
                        family_welfare_type=welfare_type.value or '',
                        family_members=[{key: field.value for key, field in fields.items()}
                                        for fields in member_rows],
                    )
                except ValidationError:
                    error_label.text = '입력 길이와 나이를 확인해 주세요. 나이는 0~150의 정수 또는 빈칸이어야 합니다.'
                    return
                saving = True
                save_button.disable()
                cancel.disable()
                error_label.text = '저장 중입니다…'
                try:
                    saved = await run.io_bound(self.students.update_family, student.id, family)
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
                ui.notify('가족 정보를 저장했습니다.', type='positive')
                if self.selected is not None and self.selected.id == saved.id:
                    await self.load_profile(saved.id)
        finally:
            self.editor_open = False
            if not dialog.is_deleted:
                dialog.delete()

    async def open_editor(self, student: Student | None = None) -> None:
        """학생 추가/수정 공통 모달. 저장 실패 시 입력을 유지하며 중복 저장을 막는다."""
        if self.editor_open:
            return
        self.editor_open = True
        try:
            school = await run.io_bound(self.school.get) if self.school is not None else SchoolSettings()
            enrollments = await run.io_bound(self.students.enrollments, student.id) if student else []
        except DatabaseError as error:
            self.editor_open = False
            ui.notify(str(error), type='negative')
            return
        grade_options = school.grade_options
        initial = student.model_dump() if student else {}
        fields = {}
        saving = False
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-2xl p-6'):
            ui.label('학생 정보 수정' if student else '새 학생 등록').classes('text-2xl font-bold')
            ui.label('학년도를 바꾸어 저장하면 해당 학년도의 학적을 추가하거나 수정합니다. 다른 학년도 이력은 유지됩니다.').classes('text-sm text-slate-500')
            with ui.column().classes('w-full gap-3'):
                with ui.row().classes('w-full flex-nowrap items-start'):
                    fields['name'] = ui.input('*이름', value=initial.get('name') or '').props('outlined').classes('flex-1 min-w-0')
                    fields['nickname'] = ui.input('별명', value=initial.get('nickname') or '').props('outlined').classes('flex-1 min-w-0')
                    fields['gender'] = ui.select(['남', '여', '기타'], label='성별',
                                                 value=initial.get('gender')).props('outlined clearable').classes('w-24 shrink-0')
                with ui.row().classes('w-full flex-nowrap items-start'):
                    fields['school_year'] = ui.number('*학년도', value=initial.get('school_year', current_school_year()),
                                                      min=1900, max=9999, step=1, precision=0).props('outlined').classes('flex-1 min-w-0')
                    grade = initial.get('grade', 1)
                    fields['grade'] = ui.select(grade_options, label='*학년',
                                                value=grade if grade in grade_options else None).props('outlined').classes('flex-1 min-w-0')
                    fields['classroom'] = ui.input('*반', value=initial.get('classroom', '')).props('outlined').classes('flex-1 min-w-0')
                    fields['student_number'] = ui.input('번호', value=initial.get('student_number') or '').props('outlined').classes('flex-1 min-w-0')
                def load_year(event):
                    for enrollment in enrollments:
                        if enrollment.school_year == event.value:
                            for key in ('grade', 'classroom', 'student_number'):
                                fields[key].value = getattr(enrollment, key)
                            break
                fields['school_year'].on_value_change(load_year)
                if grade not in grade_options:
                    ui.label(f'기존 학년은 {grade}학년입니다. 현재 학교급에 맞는 학년을 선택해야 저장할 수 있습니다.').classes('text-sm text-amber-700')
                with ui.row().classes('w-full flex-nowrap items-start'):
                    fields['birth_date'] = ui.date_input('생년월일', value=str(initial.get('birth_date') or '')).props('outlined').classes('flex-1 min-w-0')
                    fields['student_contact'] = ui.input('학생 연락처', value=initial.get('student_contact', '')).props('outlined mask="###-####-####" inputmode="numeric"').classes('flex-1 min-w-0')
                fields['notes'] = ui.textarea('학생 메모', value=initial.get('notes', '')).props('outlined').classes('w-full')
            error_label = ui.label().classes('text-red-700 text-sm whitespace-pre-wrap')

            async def save() -> None:
                nonlocal saving
                if saving:
                    return
                try:
                    value = student_form_input(dict(
                        {key: element.value for key, element in fields.items()},
                        guardian_contact=student.guardian_contact if student else ''))
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
                self.student_list.table.selected = [row for row in self.student_list.table.rows if row['id'] == saved.id]
                await self.load_profile(saved.id)
        finally:
            self.editor_open = False
            # 수정 후 프로필을 다시 그리면 그 안에서 열린 모달도 이미 제거될 수 있다.
            if not dialog.is_deleted:
                dialog.delete()
