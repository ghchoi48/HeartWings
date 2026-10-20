"""캘린더 저장, 선택 필터 및 월간/주간 탐색 검증."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from database import Database, NotFoundError
from models import CalendarInput, CalendarEventInput, CounselingInput, StudentInput
from reporting import KST
from repositories.calendar_repo import CalendarRepository
from repositories.counseling_repo import CounselingRepository
from repositories.reporting_repo import ReportingRepository
from repositories.student_repo import StudentRepository
from views.calendar_view import CalendarView


@pytest.fixture
def data(tmp_path):
    db = Database('test-only', tmp_path / 'calendar.db')
    db.initialize()
    repo = CalendarRepository(db)
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    counseling = CounselingRepository(db).create(CounselingInput(student_id=student.id, title='상담',
        starts_at=datetime(2026, 10, 20, 9, tzinfo=KST)))
    custom = repo.create(CalendarInput(name='학교 일정', color='#2563eb'))
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='회의',
        starts_at=datetime(2026, 10, 20, 10, tzinfo=KST), duration_minutes=30))
    return db, repo, custom, counseling


def test_calendar_storage_filtering_and_migration(data):
    db, repo, custom, counseling = data
    calendars = repo.list()
    assert calendars[0].source == 'counseling'
    day = date(2026, 10, 20)
    assert repo.events(day, day, []) == []
    all_events = repo.events(day, day, [c.id for c in calendars])
    assert [entry.title for entry in all_events] == ['상담', '회의']
    assert all_events[0].source == 'counseling'
    assert all_events[0].id == counseling.id
    assert [entry.title for entry in repo.events(day, day, [custom.id])] == ['회의']
    assert repo.events(day, day, [custom.id], 'completed') == []
    repo.set_visible(custom.id, False)
    db.initialize()
    assert not repo.list()[1].visible
    event = all_events[1]
    repo.save_event(CalendarEventInput(calendar_id=custom.id, title='변경한 회의',
        starts_at=datetime(2026, 10, 21, 0, tzinfo=KST)), event.id)
    assert repo.events(day, day, [custom.id]) == []
    assert repo.events(date(2026, 10, 21), date(2026, 10, 21), [custom.id])[0].title == '변경한 회의'
    with pytest.raises(NotFoundError):
        repo.save_event(CalendarEventInput(calendar_id=calendars[0].id, title='연동 캘린더에 직접 저장 불가',
            starts_at=datetime(2026, 10, 20, 9, tzinfo=KST)))
    # 이전 스키마에서 업그레이드해도 이미 있는 캘린더/일정이 보존된다.
    with db.session(write=True) as connection:
        connection.execute('PRAGMA user_version=21')
    db.initialize()
    assert len(repo.list()) == 3
    assert len(repo.events(date(2026, 10, 21), date(2026, 10, 21), [custom.id])) == 1


def test_calendar_selection_navigation_and_open(data):
    db, repo, custom, counseling = data

    async def invoke(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def check():
        with Client(page('/calendar-view-test')):
            on_open = AsyncMock()
            view = CalendarView(ReportingRepository(db), on_open)
            view.anchor = view.selected = date(2026, 10, 20)
            with patch('views.calendar_view.ui.timer'):
                view.build()
            with patch('views.calendar_view.run.io_bound', side_effect=invoke):
                await view.reload()
                assert len(view.calendars) == 3
                assert len(view.events_by_day[view.selected]) == 2
                checkboxes = [item for item in view.calendar_list.descendants() if isinstance(item, ui.checkbox)]
                assert len(checkboxes) == 3
                assert all(item.value for item in checkboxes)
                await view.toggle_calendar(custom.id, False)
                assert len(view.events_by_day[view.selected]) == 1
                await view.open_event(view.events_by_day[view.selected][0])
                on_open.assert_awaited_once_with(counseling.id)
                await view.toggle_calendar(view.calendars[0].id, False)
                assert not view.events_by_day
                await view.toggle_calendar(-1, False)
                assert '표시할 캘린더' in view.message.text
                await view.shift(1)
                assert view.anchor == date(2026, 11, 1)
                await view.shift(-1)
                assert view.anchor == date(2026, 10, 1)
                # UI 이벤트 자동 실행 없이 주간 모드 설정 후 이동을 검증한다.
                view.mode = SimpleNamespace(value='week')
                await view.shift(-1)
                assert view.anchor == date(2026, 9, 24)
                view.date_input.value = '2026-12-31'
                await view.jump()
                assert view.selected == date(2026, 12, 31)
                await view.shift(1)
                assert view.selected == date(2027, 1, 7)
                view.date_input.value = '잘못된 날짜'
                await view.jump()
                assert '올바른 날짜' in view.message.text
                await view.today()
                assert view.selected == datetime.now(KST).date()
    asyncio.run(check())


def test_slow_response_cannot_replace_new_calendar_selection():
    async def check():
        with Client(page('/calendar-stale-test')):
            view = CalendarView(Mock(), AsyncMock())
            with patch('views.calendar_view.ui.timer'):
                view.build()
            repo = Mock()
            repo.list.return_value = []
            repo.events.return_value = []
            view.repository = repo
            started, release = asyncio.Event(), asyncio.Event()
            calls = 0

            async def invoke(function, *args, **kwargs):
                nonlocal calls
                if function is repo.list:
                    calls += 1
                    if calls == 1:
                        started.set()
                        await release.wait()
                return function(*args, **kwargs)

            with patch('views.calendar_view.run.io_bound', side_effect=invoke):
                first = asyncio.create_task(view.reload())
                await started.wait()
                view.anchor = view.selected = date(2027, 1, 1)
                await view.reload()
                release.set()
                await first
                assert view.heading.text == '2027년 01월'
                repo.events.assert_called_once()
    asyncio.run(check())


def test_sunday_start_and_korean_holidays():
    from calendar_holidays import korean_holidays, is_day_off
    from views.calendar_view import visible_days

    assert visible_days(date(2026, 1, 1), 'week') == [date(2025, 12, 28), date(2025, 12, 29),
        date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert visible_days(date(2026, 3, 1), 'month')[0] == date(2026, 3, 1)
    days = korean_holidays(date(2026, 3, 1), date(2026, 3, 7))
    assert days[date(2026, 3, 1)] == '삼일절'
    assert '대체' in days[date(2026, 3, 2)]
    assert is_day_off(date(2026, 3, 2), days)
    assert is_day_off(date(2026, 3, 7), days)
    assert not is_day_off(date(2026, 3, 3), days)
    cross_year = korean_holidays(date(2025, 12, 25), date(2026, 1, 2))
    assert date(2025, 12, 25) in cross_year and date(2026, 1, 1) in cross_year


def test_holiday_calendar_visibility_and_date_colors(data):
    from calendar_holidays import HOLIDAY_CALENDAR_ID, HOLIDAY_COLOR
    db, repo, _, _ = data
    holiday = next(item for item in repo.list() if item.source == 'holidays')
    assert holiday.visible and holiday.color == HOLIDAY_COLOR

    async def check():
        with Client(page('/holiday-calendar-test')):
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = date(2026, 3, 2)
            with patch('views.calendar_view.ui.timer'):
                view.build()

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch('views.calendar_view.run.io_bound', side_effect=invoke):
                await view.reload()
                labels = [item.text for item in view.grid.descendants() if isinstance(item, ui.label)]
                assert labels[:7] == ['일', '월', '화', '수', '목', '금', '토']
                assert '삼일절 대체 휴일' in labels
                buttons = {item.text: item for item in view.grid.descendants() if isinstance(item, ui.button)}
                assert buttons['3/2']._props['color'] == 'red-7'
                assert buttons['3/7']._props['color'] == 'red-7'
                assert buttons['3/3']._props['color'] != 'red-7'
                await view.toggle_calendar(HOLIDAY_CALENDAR_ID, False)
                labels = [item.text for item in view.grid.descendants() if isinstance(item, ui.label)]
                assert '삼일절 대체 휴일' not in labels
                buttons = {item.text: item for item in view.grid.descendants() if isinstance(item, ui.button)}
                assert buttons['3/2']._props['color'] == 'red-7'
    asyncio.run(check())
    db.initialize()
    assert not next(item for item in repo.list() if item.source == 'holidays').visible
    assert len([item for item in repo.list() if item.source == 'holidays']) == 1
