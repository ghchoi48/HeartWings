import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database
from maeumnarae.core.models import SchoolSettings
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.reporting_repo import ReportingRepository
from maeumnarae.repositories.school_settings_repo import SchoolSettingsRepository
from maeumnarae.services.neis import NeisError, fetch_school_schedule
from maeumnarae.services.school_calendar import load_school_events, NEIS_CALENDAR_ID
from maeumnarae.views.calendar_view import CalendarView

DAY = date(2026, 10, 20)
ROW = {'ATPT_OFCDC_SC_CODE': 'B10', 'SD_SCHUL_CODE': '7010057', 'AA_YMD': '20261020',
       'EVENT_NM': '체육대회', 'EVENT_CNTNT': '운동장<br>준비물 안내', 'ONE_GRADE_EVENT_YN': 'Y'}


def test_schedule_pagination_filtering_and_key_required():
    with patch('maeumnarae.services.neis.request_rows', side_effect=[
        [ROW] * 100, [dict(ROW, SD_SCHUL_CODE='0000000'), dict(ROW, AA_YMD='20261021')],
    ]) as request:
        assert fetch_school_schedule('B10', '7010057', DAY, DAY, 'test-key') == [ROW] * 100
        assert request.call_args_list[1].args[1]['pIndex'] == 2
        assert request.call_args.args[1]['AA_FROM_YMD'] == '20261020'
        assert request.call_args.args[2] == 'test-key'
    with patch('maeumnarae.services.neis.request_rows') as request:
        with pytest.raises(NeisError, match='인증키'):
            fetch_school_schedule('B10', '7010057', DAY, DAY)
        request.assert_not_called()


@pytest.fixture
def db(tmp_path):
    database = Database('test-only', tmp_path / 'school-calendar.db')
    database.initialize()
    SchoolSettingsRepository(database).save(SchoolSettings(neis_office_code='B10',
        neis_school_code='7010057', neis_api_key='test-key'))
    return database


def test_visibility_persists_and_read_only_events(db):
    repo = CalendarRepository(db)
    with patch('maeumnarae.services.school_calendar.fetch_school_schedule', return_value=[ROW, ROW]) as fetch:
        assert load_school_events(db, repo.list(), DAY, DAY) == ([], '')
        fetch.assert_not_called()
        repo.set_visible(NEIS_CALENDAR_ID, True)
        db.initialize()
        events, message = load_school_events(db, repo.list(), DAY, DAY)
        assert not message and len(events) == 1
        assert events[0].all_day and events[0].duration_minutes == 1440
        assert events[0].title == '체육대회'
        assert events[0].content == '운동장\n준비물 안내\n대상 학년: 1학년'
        assert events[0].calendar_id == NEIS_CALENDAR_ID
        fetch.assert_called_once_with('B10', '7010057', DAY, DAY, 'test-key')
    with patch('maeumnarae.services.school_calendar.fetch_school_schedule', side_effect=NeisError('연결 실패')):
        assert load_school_events(db, repo.list(), DAY, DAY) == ([], '연결 실패')


def test_view_renders_schedule_details_and_failure(db):
    async def inline(fn, *args):
        return fn(*args)

    async def check():
        CalendarRepository(db).set_visible(NEIS_CALENDAR_ID, True)
        with Client(page('/school-calendar')), patch('maeumnarae.views.calendar_view.ui.timer'), \
                patch('maeumnarae.views.calendar_view.run.io_bound', side_effect=inline), \
                patch('maeumnarae.services.school_calendar.fetch_school_schedule', return_value=[ROW]) as fetch:
            view = CalendarView(ReportingRepository(db), AsyncMock())
            view.anchor = view.selected = DAY
            view.build()
            await view.reload()
            entry = view.events_by_day[DAY][0]
            assert entry.source == 'neis'
            assert any(e.props.get('aria-label') == '체육대회' for e in view.grid.descendants())
            with patch.object(view, 'open_event_editor', new_callable=AsyncMock) as editor:
                await view.open_event(entry)
                editor.assert_not_called()
            fetch.side_effect = NeisError('연결 실패')
            await view.reload()
            assert '연결 실패' in view.message.text
            assert view.calendars and view.holiday_days
            fetch.reset_mock()
            await view.toggle_calendar(NEIS_CALENDAR_ID, False)
            fetch.assert_not_called()
    asyncio.run(check())


def test_home_calendar_shares_neis_visibility(db):
    from types import SimpleNamespace
    from maeumnarae.widgets.calendar import CalendarWidget

    async def inline(fn, *args):
        return fn(*args)

    async def check():
        repo = CalendarRepository(db)
        repo.set_visible(NEIS_CALENDAR_ID, True)
        with Client(page('/school-calendar-widget')), patch('maeumnarae.widgets.calendar.ui.timer'), \
                patch('maeumnarae.widgets.calendar.run.io_bound', side_effect=inline), \
                patch('maeumnarae.services.school_calendar.fetch_school_schedule', return_value=[ROW]) as fetch:
            widget = CalendarWidget(SimpleNamespace(database=db), None, on_open_linked=AsyncMock())
            widget.anchor = widget.selected = DAY
            widget.build()
            await widget.reload()
            entry = widget.events[DAY][0]
            assert entry.title == '체육대회'
            with patch('maeumnarae.widgets.calendar.show_school_event') as details:
                await widget.open_event(entry)
                details.assert_called_once_with(entry)
                widget.on_open_linked.assert_not_called()
            repo.set_visible(NEIS_CALENDAR_ID, False)
            fetch.reset_mock()
            await widget.reload()
            assert not widget.events
            fetch.assert_not_called()
    asyncio.run(check())
