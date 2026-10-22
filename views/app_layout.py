"""사이드바와 클라이언트별 화면 전환. 화면 인스턴스를 유지해 검색 상태를 보존한다."""

from nicegui import run, ui
from collections.abc import Awaitable, Callable

from database import DatabaseError
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from views.home_view import HomeView
from repositories.home_repo import HomeRepository
from views.student_view import StudentView
from views.counseling_view import CounselingView
from views.group_counseling_view import GroupCounselingView
from repositories.group_counseling_repo import GroupCounselingRepository
from repositories.reporting_repo import ReportingRepository
from views.calendar_view import CalendarView
from views.statistics_view import StatisticsView
from views.special_education_view import SpecialEducationView
from views.consultation_view import ConsultationView
from repositories.teacher_repo import TeacherRepository
from repositories.education_event_repo import EducationEventRepository
from views.education_event_view import EducationEventView
from views.psychological_test_view import PsychologicalTestView
from views.settings_view import build_settings
from views.display_settings import DisplaySettings
from models import SchoolSettings
from repositories.school_settings_repo import SchoolSettingsRepository


class AppLayout:
    """DB를 연 클라이언트 안에서 홈, 학생 관리, 상담 일지를 조립한다."""

    def __init__(self, students: StudentRepository, counseling: CounselingRepository, reporting: ReportingRepository,
                 on_lock: Callable[[], Awaitable[None]] | None = None,
                 display: DisplaySettings | None = None,
                 on_school_change: Callable[[SchoolSettings], None] | None = None):
        self.students = students
        self.counseling = counseling
        self.reporting = reporting
        self.on_lock = on_lock
        self.display = display
        self.on_school_change = on_school_change
        self.school = SchoolSettingsRepository(students.database)
        self.active_page = 'home'
        self.student_view: StudentView | None = None
        self.counseling_view: CounselingView | None = None
        self.group_view: GroupCounselingView | None = None
        self.calendar_view: CalendarView | None = None
        self.statistics_view: StatisticsView | None = None
        self.consultation_view: ConsultationView | None = None
        self.special_education_view: SpecialEducationView | None = None
        self.education_event_view: EducationEventView | None = None
        self.psychological_test_view: PsychologicalTestView | None = None
        self.opening_schedule = False
        self.panels = {}
        self.buttons = {}
        self.student_revision = students.database.student_revision
        self.refreshing_students = False

    def build(self, content: ui.column, drawer: ui.left_drawer, header: ui.header) -> None:
        """최상위 레이아웃 요소는 진입점에서 생성하고 여기서는 내용만 구성한다."""
        drawer.classes('flex flex-col flex-nowrap')
        with drawer:
            for page, title, icon in [('home', '홈', 'home'), ('students', '학생 관리', 'school'),
                                      ('groups', '집단 상담', 'groups'),
                                      ('education_events', '교육/행사', 'event'),
                                      ('special_education', '특별교육', 'menu_book'),
                                      ('consultation', '자문', 'forum'),
                                      ('calendar', '캘린더', 'calendar_month'),
                                      ('statistics', '통계', 'bar_chart'),
                                      ('settings', '설정', 'settings')]:
                if page == 'settings':
                    ui.space().classes('min-h-4')
                self.buttons[page] = ui.button(
                    title, icon=icon, on_click=lambda page=page: self.navigate(page),
                ).props('flat align=left').classes('w-full rounded-lg')
                if page in ('students', 'consultation'):
                    ui.separator()
        with header:
            ui.button('DB 잠금', icon='lock', on_click=self.on_lock or (lambda: ui.navigate.to('/'))).props('flat color=white').classes('ml-auto rounded-lg')
        with content:
            self.panels['home'] = ui.column().classes('w-full')
            with self.panels['home']:
                self.home_view = HomeView(HomeRepository(self.students.database,
                                                          self.display.store if self.display else None),
                                          TeacherRepository(self.students.database),
                                          lambda: self.navigate('students'))
                self.home_view.build()
            self.panels['students'] = ui.column().classes('w-full')
            self.panels['counseling'] = ui.column().classes('w-full')
            self.panels['groups'] = ui.column().classes('w-full')
            self.panels['special_education'] = ui.column().classes('w-full')
            self.panels['consultation'] = ui.column().classes('w-full')
            self.panels['education_events'] = ui.column().classes('w-full')
            self.panels['settings'] = ui.column().classes('w-full')
            with self.panels['settings']:
                build_settings(self.display, self.school, self.students.database, self.on_school_change,
                               self.refresh_roster)
            self.panels['calendar'] = ui.column().classes('w-full')
            self.panels['statistics'] = ui.column().classes('w-full')
        self.navigate('home')
        with content:
            ui.timer(0.5, self.refresh_students)

    async def refresh_roster(self, kind: str) -> None:
        if kind == 'students':
            await self.refresh_students()
        elif self.consultation_view is not None:
            await self.consultation_view.reload()

    async def refresh_students(self) -> None:
        """커밋된 학생 변경을 숨겨진 화면에도 반영하고 편집 중에는 갱신을 미룬다."""
        revision = self.students.database.student_revision
        if self.refreshing_students or revision == self.student_revision:
            return
        if any(view and view.editor_open for view in
               (self.student_view, self.counseling_view, self.group_view, self.special_education_view, self.psychological_test_view)):
            return
        self.refreshing_students = True
        try:
            if self.student_view:
                await self.student_view.student_list.reload()
                if self.student_view.selected:
                    await self.student_view.load_profile(self.student_view.selected.id)
            for view in (self.counseling_view, self.special_education_view, self.psychological_test_view):
                if view is None:
                    continue
                if hasattr(view, 'student_list'):
                    await view.student_list.reload()
                if view.selected:
                    selected_id = view.selected.id
                    student = await run.io_bound(self.students.get, selected_id)
                    if view.selected and view.selected.id == selected_id:
                        if student is None:
                            await view.select_student(None)
                        else:
                            view.selected = student
                            view.student_heading.text = f'{student.name} · {student.grade}학년 {student.classroom}반'
            if self.group_view and self.group_view.selected:
                await self.group_view.select_group(self.group_view.selected.id)
            if self.calendar_view:
                await self.calendar_view.reload()
            if self.statistics_view:
                await self.statistics_view.load()
            self.student_revision = revision
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            self.refreshing_students = False

    def navigate(self, page: str) -> None:
        """화면을 다시 만들지 않고 전환한다. 학생 화면은 최초 진입 시에만 생성한다."""
        if page not in self.panels:
            raise ValueError(f'지원하지 않는 화면: {page}')
        if page == 'students' and self.student_view is None:
            with self.panels['students']:
                self.student_view = StudentView(self.students, self.counseling, self.school, self.open_student_counseling)
                self.student_view.build()
        if page == 'counseling' and self.counseling_view is None:
            with self.panels['counseling']:
                with ui.row().classes('w-full items-center justify-between px-8 pt-6'):
                    counseling_heading = ui.label('일지 관리').classes('text-3xl font-bold text-slate-800')
                    ui.button('학생 관리', icon='arrow_back', on_click=lambda: self.navigate('students')).props('outline')
                with ui.tabs().classes('w-full') as self.counseling_tabs:
                    ui.tab('logs', label='상담 일지', icon='edit_note')
                    ui.tab('tests', label='심리 검사', icon='psychology')
                self.psychological_test_view = PsychologicalTestView(self.students)
                self.counseling_view = CounselingView(
                    self.students, self.counseling, self.refresh_student_timeline,
                    self.psychological_test_view.select_student)
                counseling_heading.bind_text_from(
                    self.counseling_view, 'selected',
                    backward=lambda student: (
                        f'{student.name} · {student.grade}학년 {student.classroom}반'
                        if student else '일지 관리'
                    ),
                )
                with ui.tab_panels(self.counseling_tabs, value='logs').classes('w-full bg-transparent'):
                    with ui.tab_panel('logs').classes('p-0'):
                        self.counseling_view.build()
                        self.counseling_view.student_heading.set_visibility(False)
                    with ui.tab_panel('tests').classes('p-0'):
                        self.psychological_test_view.build(embedded=True)
        if page == 'groups' and self.group_view is None:
            with self.panels['groups']:
                self.group_view = GroupCounselingView(GroupCounselingRepository(self.counseling.database), self.refresh_group_timeline)
                self.group_view.build()
        if page == 'special_education' and self.special_education_view is None:
            with self.panels['special_education']:
                self.special_education_view = SpecialEducationView(self.students, self.refresh_student_timeline)
                self.special_education_view.build()
        if page == 'calendar' and self.calendar_view is None:
            with self.panels['calendar']:
                self.calendar_view = CalendarView(self.reporting, self.open_schedule)
                self.calendar_view.build()
        if page == 'consultation' and self.consultation_view is None:
            with self.panels['consultation']:
                self.consultation_view = ConsultationView(TeacherRepository(self.students.database))
                self.consultation_view.build()
        if page == 'education_events' and self.education_event_view is None:
            with self.panels['education_events']:
                self.education_event_view = EducationEventView(EducationEventRepository(self.students.database))
                self.education_event_view.build()
        if page == 'statistics' and self.statistics_view is None:
            with self.panels['statistics']:
                self.statistics_view = StatisticsView(self.reporting)
                self.statistics_view.build()
        if page == 'home' and hasattr(self, 'home_view'):
            with self.panels['home']:
                for widget in self.home_view.widget_views:
                    if widget.kind == 'meal':
                        ui.timer(0, widget.reload, once=True)
        self.active_page = page
        for name, panel in self.panels.items():
            panel.set_visibility(name == page)
        for name, button in self.buttons.items():
            if name == page:
                button.classes(add='bg-primary font-bold')
                # Quasar의 flat 버튼 text-primary보다 대비 색상을 우선한다.
                button.style('color: var(--app-primary-text, #ffffff) !important')
                button.props('aria-current=page')
            else:
                button.classes(remove='bg-primary font-bold')
                button.style(remove='color:')
                button.props(remove='aria-current')

    async def open_student_counseling(self, student_id: int) -> None:
        """학생 관리에서 선택한 학생의 상담 사례와 심리검사를 함께 연다."""
        self.navigate('counseling')
        self.counseling_tabs.set_value('logs')
        await self.counseling_view.select_student(student_id)

    async def refresh_group_timeline(self) -> None:
        """참여자 변경과 일지 저장을 열려 있는 학생 타임라인에 반영한다."""
        if self.student_view and self.student_view.selected:
            await self.student_view.load_profile(self.student_view.selected.id)

    async def refresh_student_timeline(self, student_id: int) -> None:
        """상담 저장 후 열려 있는 관련 뷰의 스냅샷도 갱신한다."""
        if self.student_view and self.student_view.selected and self.student_view.selected.id == student_id:
            await self.student_view.load_profile(student_id)
        if self.calendar_view:
            await self.calendar_view.reload()
        if self.statistics_view:
            await self.statistics_view.load()

    async def open_schedule(self, entry_id: int) -> None:
        """캘린더의 기존 일지를 공용 상담 편집기로 연다."""
        if self.opening_schedule:
            return
        self.opening_schedule = True
        try:
            self.navigate('counseling')
            self.counseling_tabs.set_value('logs')
            await self.counseling_view.open_record(entry_id)
        finally:
            self.opening_schedule = False
