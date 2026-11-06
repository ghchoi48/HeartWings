"""일정 추가 창의 예약 일지 전용 입력."""
from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.journals.case_repo import CaseRepository
from maeumnarae.repositories.journals.special_education_repo import SpecialEducationRepository
from maeumnarae.services.calendar.calendar_reservations import KINDS
from maeumnarae.views.shared.time_inputs import time_input


class ReservationFields:
    def __init__(self, database, options, current_time, duration, time_row):
        self.database = database
        self.loading = False
        self.failed = False
        self.request = 0
        self.saving = False
        students, teachers, groups = options
        with ui.column().classes('w-full') as self.panel:
            self.kind = ui.select(KINDS, label='일지 종류', value='individual').props('outlined').classes('w-full')
            self.student = ui.select(students, label='학생', with_input=True).props('outlined clearable').classes('w-full')
            self.teacher = ui.select(teachers, label='교직원', with_input=True).props('outlined clearable').classes('w-full')
            self.group = ui.select(groups, label='집단', with_input=True).props('outlined clearable').classes('w-full')
            self.case = ui.select({}, label='상담 사례').props('outlined').classes('w-full')
            self.hint = ui.label().classes('text-sm text-slate-500')
            with time_row:
                self.start = time_input('시작 시각', value=current_time.strftime('%H:%M')).props('outlined').classes('flex-1 min-w-0')
                self.duration = ui.number('시간 (분)', value=duration, min=1, max=1440, step=1).props('outlined').classes('flex-1 min-w-0')
        self.fields = (self.kind, self.student, self.teacher, self.group, self.case, self.start, self.duration)
        self.kind.on_value_change(self.refresh)
        self.student.on_value_change(self.refresh)
        self.update_visibility()

    def update_visibility(self):
        kind = self.kind.value
        student_kind = kind in ('individual', 'special_education')
        self.student.set_visibility(student_kind)
        self.teacher.set_visibility(kind == 'consultation')
        self.group.set_visibility(kind == 'group')
        self.case.set_visibility(student_kind)
        self.case.set_enabled(not self.saving and not self.loading and bool(self.case.options))
        self.case.set_label('특별교육' if kind == 'special_education' else '상담 사례')
        if not student_kind:
            self.hint.text = '선택할 항목이 없으면 해당 관리 화면에서 먼저 등록해 주세요.'
        elif self.failed:
            self.hint.text = '목록을 불러오지 못했습니다. 학생을 다시 선택해 주세요.'
        elif self.loading:
            self.hint.text = '목록을 불러오는 중입니다.'
        elif not self.student.value:
            self.hint.text = '학생을 선택해 주세요.'
        elif not self.case.options:
            self.hint.text = ('저장 시 기본 상담 사례를 자동 생성합니다.' if kind == 'individual'
                              else '먼저 학생의 특별교육을 등록해 주세요.')
        else:
            self.hint.text = ''

    async def refresh(self):
        self.request += 1
        request = self.request
        self.case.set_options({}, value=None)
        self.failed = False
        student_id, kind = self.student.value, self.kind.value
        self.loading = bool(student_id and kind in ('individual', 'special_education'))
        self.update_visibility()
        if not self.loading:
            return
        try:
            repo = CaseRepository(self.database) if kind == 'individual' else SpecialEducationRepository(self.database)
            cases = await run.io_bound(repo.list, student_id)
            if request != self.request or self.panel.is_deleted:
                return
            self.case.set_options({item.id: item.title for item in cases},
                                  value=cases[0].id if len(cases) == 1 else None)
        except DatabaseError:
            if request == self.request and not self.panel.is_deleted:
                self.failed = True
        finally:
            if request == self.request and not self.panel.is_deleted:
                self.loading = False
                self.update_visibility()

    def values(self):
        if self.loading or self.failed:
            raise ValueError('대상 목록을 확인한 후 저장해 주세요.')
        kind = self.kind.value
        owner = self.group if kind == 'group' else self.teacher if kind == 'consultation' else self.student
        return dict(kind=kind, owner_id=owner.value,
                    case_id=self.case.value if kind in ('individual', 'special_education') else None,
                    duration_minutes=self.duration.value)
