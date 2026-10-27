"""Calendar widget navigation, filtering, refresh and lifecycle tests."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import Client
from nicegui.page import page

from maeumnarae.services.calendar_dates import shift_month, visible_days, events_by_date
from maeumnarae.services.reporting import KST
from maeumnarae.widgets.calendar import CalendarWidget
from maeumnarae.views.home_layout import DEFAULT_SIZES
from maeumnarae.repositories.home_repo import HomeRepository
from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.core.models import CalendarInput, CalendarEventInput
from maeumnarae.repositories.calendar_repo import CalendarRepository


def test_month_boundaries_and_midnight():
    assert shift_month(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert shift_month(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert shift_month(date(2025, 12, 31), 1) == date(2026, 1, 31)
    days = visible_days(date(2026, 10, 1), 'month')
    assert days[0].weekday() == 6 and days[-1].weekday() == 5
    entry = SimpleNamespace(starts_at=datetime(2026, 10, 1, 0, tzinfo=KST), duration_minutes=2880)
    assert list(events_by_date([entry], days)) == [date(2026, 10, 1), date(2026, 10, 2)]
    assert DEFAULT_SIZES['calendar'] == (8, 520)
    assert HomeRepository.normalize_layout([{'kind': 'calendar', 'span': 1}])[0]['kind'] == 'calendar'


def test_widget_filters_navigation_editing_and_refresh():
    async def invoke(fn, *args):
        return fn(*args)

    async def check():
        with Client(page('/calendar-widget-test')), patch('maeumnarae.widgets.calendar.ui.timer'), \
                patch('maeumnarae.widgets.calendar.run.io_bound', side_effect=invoke):
            home = SimpleNamespace(database=SimpleNamespace(write_revision=1))
            widget = CalendarWidget(home, None, on_open=AsyncMock(), on_open_linked=AsyncMock())
            widget.build()
            widget.repository.list = Mock(return_value=[
                SimpleNamespace(id=1, source='custom', visible=True),
                SimpleNamespace(id=2, source='custom', visible=False),
                SimpleNamespace(id=-1, source='holidays', visible=False)])
            widget.repository.events = Mock(return_value=[])
            widget.anchor = widget.selected = date(2026, 1, 31)
            await widget.reload()
            assert widget.repository.events.call_args.args[2] == [1]
            assert widget.holidays == {}
            await widget.shift(1)
            assert widget.selected == date(2026, 2, 28)
            await widget.choose(date(2026, 3, 1))
            assert widget.anchor == date(2026, 3, 1)
            for source in ['counseling', 'group', 'consultation', 'special_education']:
                await widget.open_event(SimpleNamespace(source=source, id=5))
            widget.on_open.assert_awaited_once_with(5)
            assert widget.on_open_linked.await_count == 3
            with patch('maeumnarae.widgets.calendar.open_event_editor', new=AsyncMock()) as editor:
                await widget.edit()
                assert editor.await_args.args[2] == date(2026, 3, 1)
                assert not widget.editor_open
            with patch.object(widget, 'reload', new=AsyncMock()) as reload:
                await widget.refresh_if_changed()
                reload.assert_not_awaited()
                home.database.write_revision += 1
                widget.editor_open = True
                await widget.refresh_if_changed()
                reload.assert_not_awaited()
                widget.editor_open = False
                await widget.refresh_if_changed()
                reload.assert_awaited_once()
                reload.reset_mock()
                widget.body.delete()
                await widget.refresh_if_changed()
                reload.assert_not_awaited()
    asyncio.run(check())


def test_stale_load_does_not_replace_new_month():
    async def check():
        with Client(page('/calendar-widget-stale')), patch('maeumnarae.widgets.calendar.ui.timer'):
            widget = CalendarWidget(SimpleNamespace(database=SimpleNamespace(write_revision=1)), None)
            widget.build()
            widget.repository.list = Mock(return_value=[])
            widget.repository.events = Mock(return_value=[])
            started, release = asyncio.Event(), asyncio.Event()
            calls = 0

            async def invoke(fn):
                nonlocal calls
                calls += 1
                result = fn()
                if calls == 1:
                    started.set()
                    await release.wait()
                return result

            with patch('maeumnarae.widgets.calendar.run.io_bound', side_effect=invoke):
                task = asyncio.create_task(widget.reload())
                await started.wait()
                await widget.shift(1)
                heading = widget.heading.text
                release.set()
                await task
                assert widget.heading.text == heading
                assert not widget.loading
    asyncio.run(check())


def test_database_updates_multiple_widgets_and_errors(tmp_path):
    async def invoke(fn, *args):
        return fn(*args)

    async def check():
        db = Database('test-only', tmp_path / 'widget.db')
        db.initialize()
        repo = CalendarRepository(db)
        custom = repo.create(CalendarInput(name='School', color='#2563eb'))
        day = date(2026, 10, 20)
        with Client(page('/calendar-widget-db')), patch('maeumnarae.widgets.calendar.ui.timer'), \
                patch('maeumnarae.widgets.calendar.run.io_bound', side_effect=invoke):
            widgets = [CalendarWidget(HomeRepository(db), None) for _ in range(2)]
            for widget in widgets:
                widget.build()
                widget.anchor = widget.selected = day
                await widget.reload()
            repo.save_event(CalendarEventInput(calendar_id=custom.id, title='Meeting',
                            starts_at=datetime(2026, 10, 20, 9, tzinfo=KST)))
            for widget in widgets:
                await widget.refresh_if_changed()
                assert widget.events[day][0].title == 'Meeting'
            repo.set_visible(custom.id, False)
            for widget in widgets:
                await widget.refresh_if_changed()
                assert not widget.events
            await widgets[0].shift(1)
            assert widgets[1].selected == day
            with patch.object(widgets[0].repository, 'list', side_effect=DatabaseError('test error')):
                await widgets[0].reload()
                assert 'test error' in widgets[0].message.text
                assert not widgets[0].loading
            await widgets[0].reload()
            assert 'test error' not in widgets[0].message.text
    asyncio.run(check())
