"""사이드바와 클라이언트별 화면 전환. 화면 인스턴스를 유지해 검색 상태를 보존한다."""

from nicegui import ui
from collections.abc import Awaitable, Callable

from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from views.home_view import build_home
from views.student_view import StudentView
from views.counseling_view import CounselingView
from repositories.reporting_repo import ReportingRepository
from views.calendar_view import CalendarView
from views.statistics_view import StatisticsView


class AppLayout:
    """DB를 연 클라이언트 안에서 홈, 학생 관리, 상담 일지를 조립한다."""

    def __init__(self, students: StudentRepository, counseling: CounselingRepository, reporting: ReportingRepository,
                 on_lock: Callable[[], Awaitable[None]] | None = None):
        self.students = students
        self.counseling = counseling
        self.reporting = reporting
        self.on_lock = on_lock
        self.active_page = 'home'
        self.student_view: StudentView | None = None
        self.counseling_view: CounselingView | None = None
        self.calendar_view: CalendarView | None = None
        self.statistics_view: StatisticsView | None = None
        self.opening_schedule = False
        self.panels = {}
        self.buttons = {}

    def build(self, content: ui.column, drawer: ui.left_drawer) -> None:
        """최상위 레이아웃 요소는 진입점에서 생성하고 여기서는 내용만 구성한다."""
        with drawer:
            for page, title, icon in [('home', '홈', 'home'), ('students', '학생 관리', 'school'),
                                      ('counseling', '상담 일지', 'edit_note'), ('calendar', '캘린더', 'calendar_month'),
                                      ('statistics', '통계', 'bar_chart')]:
                self.buttons[page] = ui.button(
                    title, icon=icon, on_click=lambda page=page: self.navigate(page),
                ).props('flat align=left').classes('w-full rounded-lg')
            ui.separator().classes('my-4')
            ui.button('DB 잠금', icon='lock', on_click=self.on_lock or (lambda: ui.navigate.to('/'))).props('flat align=left').classes('w-full text-slate-500 rounded-lg')
        with content:
            self.panels['home'] = ui.column().classes('w-full')
            with self.panels['home']:
                build_home(lambda: self.navigate('students'))
            self.panels['students'] = ui.column().classes('w-full')
            self.panels['counseling'] = ui.column().classes('w-full')
            self.panels['calendar'] = ui.column().classes('w-full')
            self.panels['statistics'] = ui.column().classes('w-full')
        self.navigate('home')

    def navigate(self, page: str) -> None:
        """화면을 다시 만들지 않고 전환한다. 학생 화면은 최초 진입 시에만 생성한다."""
        if page not in self.panels:
            raise ValueError(f'지원하지 않는 화면: {page}')
        if page == 'students' and self.student_view is None:
            with self.panels['students']:
                self.student_view = StudentView(self.students, self.counseling)
                self.student_view.build()
        if page == 'counseling' and self.counseling_view is None:
            with self.panels['counseling']:
                self.counseling_view = CounselingView(self.students, self.counseling, self.refresh_student_timeline)
                self.counseling_view.build()
        if page == 'calendar' and self.calendar_view is None:
            with self.panels['calendar']:
                self.calendar_view = CalendarView(self.reporting, self.open_schedule)
                self.calendar_view.build()
        if page == 'statistics' and self.statistics_view is None:
            with self.panels['statistics']:
                self.statistics_view = StatisticsView(self.reporting)
                self.statistics_view.build()
        self.active_page = page
        for name, panel in self.panels.items():
            panel.set_visibility(name == page)
        for name, button in self.buttons.items():
            if name == page:
                button.classes(add='bg-teal-50 text-teal-800 font-bold')
                button.props('aria-current=page')
            else:
                button.classes(remove='bg-teal-50 text-teal-800 font-bold')
                button.props(remove='aria-current')

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
            await self.counseling_view.open_record(entry_id)
        finally:
            self.opening_schedule = False
