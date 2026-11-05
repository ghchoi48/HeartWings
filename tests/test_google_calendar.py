"""Google ICS behavior without real credentials or network requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import ssl
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import AsyncMock, Mock, patch

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.core.models import CalendarInput
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.google_calendar_repo import GoogleCalendarRepository, validate_url
from maeumnarae.services import google_calendar as service
from maeumnarae.views.calendar_view import week_event_segments

URL = 'https://calendar.google.com/calendar/ical/example%40gmail.com/private-test/basic.ics'
DAY = date(2026, 11, 5)
ROW = {'id': 1, 'name': '테스트', 'color': '#4285f4'}


def feed(*events, zone='Asia/Seoul'):
    text = 'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Tests//EN\nX-WR-TIMEZONE:' + zone + '\n'
    for event in events:
        text += 'BEGIN:VEVENT\n' + event + '\nEND:VEVENT\n'
    return (text + 'END:VCALENDAR\n').replace('\n', '\r\n').encode()


SIMPLE = feed('UID:one\nDTSTART:20261105T000000Z\nDTEND:20261105T010000Z\nSUMMARY:회의\nLOCATION:상담실\nDESCRIPTION:내용')


class ParsingTests(unittest.TestCase):
    def parse(self, raw, start=DAY, end=DAY):
        return service.events_from_ics(raw, ROW, start, end)

    def test_timed_and_stable_identity(self):
        event, = self.parse(SIMPLE)
        self.assertEqual((event.starts_at.hour, event.duration_minutes, event.location), (9, 60, '상담실'))
        self.assertEqual(event.source, 'google_ics')
        self.assertEqual(event.calendar_id, -3)
        self.assertEqual(self.parse(SIMPLE)[0].id, event.id)

    def test_all_day_exclusive_end_and_overlap(self):
        raw = feed('UID:all\nDTSTART;VALUE=DATE:20261104\nDTEND;VALUE=DATE:20261106')
        event, = self.parse(raw)
        self.assertTrue(event.all_day)
        self.assertEqual(event.duration_minutes, 2880)
        self.assertEqual(self.parse(raw, date(2026, 11, 6), date(2026, 11, 6)), [])

    def test_midnight_end_not_in_next_day(self):
        raw = feed('UID:x\nDTSTART:20261104T140000Z\nDTEND:20261104T150000Z')
        self.assertEqual(self.parse(raw), [])

    def test_recurrence_exclusion_override_and_cancellation(self):
        raw = feed(
            'UID:r\nDTSTART:20261101T000000Z\nDTEND:20261101T010000Z\nRRULE:FREQ=DAILY;COUNT=7\nEXDATE:20261102T000000Z',
            'UID:r\nRECURRENCE-ID:20261103T000000Z\nDTSTART:20261103T020000Z\nDTEND:20261103T030000Z\nSUMMARY:변경',
            'UID:r\nRECURRENCE-ID:20261104T000000Z\nDTSTART:20261104T000000Z\nSTATUS:CANCELLED')
        events = self.parse(raw, date(2026, 11, 1), date(2026, 11, 7))
        self.assertEqual([e.starts_at.day for e in events], [1, 3, 5, 6, 7])
        self.assertEqual(events[1].starts_at.hour, 11)
        self.assertEqual(len({e.id for e in events}), 5)

    def test_dst_and_floating_timezone(self):
        raw = feed('UID:dst\nDTSTART:20261031T090000\nDTEND:20261031T100000\nRRULE:FREQ=DAILY;COUNT=3', zone='America/New_York')
        events = self.parse(raw, date(2026, 10, 31), date(2026, 11, 3))
        self.assertEqual([e.starts_at.hour for e in events], [22, 23, 23])

    def test_floating_default_and_empty_calendar(self):
        raw = feed('UID:f\nDTSTART:20261105T090000').replace(b'X-WR-TIMEZONE:Asia/Seoul\r\n', b'')
        self.assertEqual(self.parse(raw)[0].starts_at.hour, 9)
        self.assertEqual(self.parse(feed()), [])

    def test_floating_exdate_and_rdate_without_calendar_timezone(self):
        raw = feed('UID:f\nDTSTART:20261105T090000\nDTEND:20261105T100000\nRRULE:FREQ=DAILY;COUNT=3\nEXDATE:20261106T090000\nRDATE:20261109T090000')
        raw = raw.replace(b'X-WR-TIMEZONE:Asia/Seoul\r\n', b'')
        events = self.parse(raw, DAY, date(2026, 11, 10))
        self.assertEqual([e.starts_at.day for e in events], [5, 7, 9])

    def test_invalid_feed_sanitized(self):
        for raw in (b'<html>secret</html>', feed('UID:x\nSUMMARY:missing start')):
            with self.assertRaises(service.GoogleCalendarError) as caught:
                self.parse(raw)
            self.assertNotIn('secret', str(caught.exception))

    def test_same_uid_in_multiple_calendars_keeps_both_segments(self):
        raw = feed('UID:shared\nDTSTART;VALUE=DATE:20261105\nDTEND;VALUE=DATE:20261106')
        first, = self.parse(raw)
        second, = service.events_from_ics(raw, {**ROW, 'id': 2}, DAY, DAY)
        self.assertEqual(len(week_event_segments([DAY], {DAY: [first, second]})), 2)


class DownloadTests(unittest.TestCase):
    def test_certificate_failure_is_specific_sanitized_and_not_retried(self):
        for error in (ssl.SSLCertVerificationError(URL), URLError(ssl.SSLCertVerificationError(URL))):
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(service, 'build_opener', return_value=opener), \
                    patch.object(service, 'ssl_context') as context, \
                    patch.object(service, 'HTTPSHandler') as handler:
                with self.assertRaisesRegex(service.GoogleCalendarError, '인증서') as caught:
                    service.download(URL)
                handler.assert_called_once_with(context=context.return_value)
                opener.open.assert_called_once()
                self.assertNotIn(URL, str(caught.exception))

    def test_http_error_is_distinct_from_certificate_error(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(URL, 404, 'missing', {}, None)
        with patch.object(service, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(service.GoogleCalendarError, 'HTTP 404') as caught:
                service.download(URL)
        self.assertNotIn(URL, str(caught.exception))

    def test_private_google_urls_only(self):
        self.assertEqual(validate_url(' ' + URL + ' '), URL)
        for bad in (URL.replace('https:', 'http:'), URL.replace('calendar.google.com', 'evil.test'),
                    URL.replace('private-test', 'public'), URL + '?x=1', URL + '#x',
                    URL.replace('calendar.google.com', 'calendar.google.com@evil.test'), URL + '\nsecret'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_url(bad)

    def test_download_success_limit_and_sanitized_network_error(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(service, 'build_opener', return_value=opener):
            response.read.side_effect = [SIMPLE, b'']
            self.assertEqual(service.download(URL), SIMPLE)
            response.read.side_effect = [b'x' * 50]
            with patch.object(service, 'MAX_BYTES', 20), self.assertRaises(service.GoogleCalendarError):
                service.download(URL)
            opener.open.side_effect = OSError(URL)
            with self.assertRaises(service.GoogleCalendarError) as caught:
                service.download(URL)
            self.assertNotIn(URL, str(caught.exception))

    def test_redirect_rejected(self):
        with self.assertRaises(service.GoogleCalendarError):
            service.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test/')


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.db'
        self.db = Database('test-password', self.path)
        self.db.initialize()
        self.repo = GoogleCalendarRepository(self.db)
        self.value = CalendarInput(name='구글', color='#4285f4')
        self.id = self.repo.save(self.value, URL, SIMPLE, datetime.now(timezone.utc).isoformat())

    def load(self, force=False):
        return service.load_google_events(self.db, CalendarRepository(self.db).list(), DAY, DAY, force)

    def test_cache_restart_visibility_delete_and_migration(self):
        self.db.initialize()
        restarted = Database('test-password', self.path)
        restarted.initialize()
        self.assertEqual(len(GoogleCalendarRepository(restarted).calendars()), 1)
        with patch.object(service, 'download') as download:
            self.assertEqual(len(self.load()[0]), 1)
            download.assert_not_called()
            CalendarRepository(self.db).set_visible(-self.id - 2, False)
            self.assertEqual(self.load(True)[0], [])
            download.assert_not_called()
        self.repo.delete(self.id)
        self.assertIsNone(self.repo.get(self.id))
        # Simulate an existing v1 DB lacking the new table.
        with self.db.session(write=True) as connection:
            connection.execute('DROP TABLE google_calendar_subscriptions')
            connection.execute('PRAGMA user_version = 1')
        self.db.initialize()
        self.assertEqual(self.repo.list(), [])

    def test_manual_refresh_empty_snapshot_and_interval(self):
        with patch.object(service, 'download', return_value=feed()) as download:
            self.assertEqual(self.load(True)[0], [])
            self.load()
            self.assertEqual(download.call_count, 1)
            with self.db.session(write=True) as connection:
                connection.execute('UPDATE google_calendar_subscriptions SET checked_at=?',
                                   ((datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(),))
            self.load()
            self.assertEqual(download.call_count, 2)

    def test_failure_retains_last_good_and_retries_only_when_due(self):
        with patch.object(service, 'download', side_effect=service.GoogleCalendarError('연결 실패')) as download:
            events, message = self.load(True)
            self.assertEqual(len(events), 1)
            self.assertIn('연결 실패', message)
            self.load()
            self.assertEqual(download.call_count, 1)
            self.assertEqual(self.repo.get(self.id)['ics'], SIMPLE)

    def test_malformed_snapshot_does_not_replace_cache(self):
        with patch.object(service, 'download', return_value=b'not ics'):
            self.assertEqual(len(self.load(True)[0]), 1)
        self.assertEqual(self.repo.get(self.id)['ics'], SIMPLE)

    def test_duplicate_and_edit(self):
        with self.assertRaises(ValueError):
            self.repo.save(self.value, URL, SIMPLE, datetime.now(timezone.utc).isoformat())
        old = self.repo.get(self.id)
        self.repo.save(CalendarInput(name='변경'), URL.replace('private-test', 'private-new'), feed(),
                       datetime.now(timezone.utc).isoformat(), self.id)
        self.repo.store_result(old, datetime.now(timezone.utc).isoformat(), SIMPLE)
        self.assertEqual(self.repo.get(self.id)['ics'], feed())
        self.assertEqual(self.repo.get(self.id)['name'], '변경')

    def test_deleted_subscription_not_recreated_by_late_result(self):
        def delete_during_download(url):
            self.repo.delete(self.id)
            return SIMPLE
        with patch.object(service, 'download', side_effect=delete_during_download):
            self.assertEqual(self.load(True)[0], [])
        self.assertIsNone(self.repo.get(self.id))

    def test_address_edit_during_fetch_discards_late_response(self):
        def edit_during_download(url):
            self.repo.save(self.value, URL.replace('private-test', 'private-new'), feed(),
                           datetime.now(timezone.utc).isoformat(), self.id)
            return SIMPLE
        with patch.object(service, 'download', side_effect=edit_during_download):
            self.assertEqual(self.load(True)[0], [])
        self.assertEqual(self.repo.get(self.id)['ics'], feed())

    def test_one_failed_subscription_does_not_hide_others(self):
        self.repo.save(self.value, URL.replace('private-test', 'private-other'), SIMPLE,
                       datetime.now(timezone.utc).isoformat())
        with patch.object(service, 'download', side_effect=[service.GoogleCalendarError('연결 실패'), SIMPLE]):
            events, message = self.load(True)
        self.assertEqual(len(events), 2)
        self.assertEqual(len({e.calendar_id for e in events}), 2)
        self.assertIn('연결 실패', message)

    def test_concurrent_force_refresh_is_coalesced(self):
        entered, release, second_started = Event(), Event(), Event()
        calendars = CalendarRepository(self.db).list()
        def slow_download(url):
            entered.set()
            self.assertTrue(release.wait(10))
            return SIMPLE
        real_guard = service._guard
        class Guard:
            count = 0
            def __enter__(self):
                real_guard.acquire()
                self.count += 1
                if self.count == 2:
                    second_started.set()
            def __exit__(self, *args):
                real_guard.release()
        def load():
            return service.load_google_events(self.db, calendars, DAY, DAY, True)
        with patch.object(service, '_guard', Guard()), patch.object(service, 'download', side_effect=slow_download) as download, ThreadPoolExecutor(2) as pool:
            first = pool.submit(load)
            self.assertTrue(entered.wait(10))
            other = pool.submit(load)
            self.assertTrue(second_started.wait(10))
            release.set()
            self.assertEqual(len(first.result()[0]), 1)
            self.assertEqual(len(other.result()[0]), 1)
            self.assertEqual(download.call_count, 1)

    def test_lock_blocks_fetch(self):
        calendars = CalendarRepository(self.db).list()
        self.db.lock()
        with patch.object(service, 'download') as download, self.assertRaises(DatabaseError):
            service.load_google_events(self.db, calendars, DAY, DAY, True)
        download.assert_not_called()


class ScreenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from maeumnarae.views.calendar_view import CalendarView
        from maeumnarae.widgets.calendar import CalendarWidget
        SubscriptionTests.setUp(self)
        home = SimpleNamespace(database=self.db)
        self.view = CalendarView(home, AsyncMock())
        self.widget = CalendarWidget(home, [])
        self.view.anchor = self.widget.anchor = DAY
        for target in (self.view, self.widget):
            target.heading = Mock()
            target.message = Mock(text='')
        self.view.grid = Mock(is_deleted=False)
        self.view.mode = SimpleNamespace(value='month')
        self.view.previous_button = self.view.next_button = Mock()
        self.view.render_calendars = Mock()
        self.view.render_grid = Mock()
        self.widget.body = Mock(is_deleted=False)
        self.widget.add = Mock()
        self.widget.render = Mock()

    async def test_home_and_full_view_share_cached_events(self):
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)
        with patch('nicegui.run.io_bound', side_effect=inline), patch.object(service, 'download') as download:
            await self.view.reload()
            await self.widget.reload()
        first = [e for e in self.view.events_by_day[DAY] if e.source == 'google_ics']
        second = [e for e in self.widget.events[DAY] if e.source == 'google_ics']
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        download.assert_not_called()

    async def test_read_only_routing_and_drag(self):
        event, = service.events_from_ics(SIMPLE, ROW, DAY, DAY)
        self.view.open_event_editor = AsyncMock()
        self.widget.edit = AsyncMock()
        with patch('maeumnarae.views.calendar_view.show_google_event') as full, \
                patch('maeumnarae.widgets.calendar.show_google_event') as home:
            await self.view.open_event(event)
            await self.widget.open_event(event)
        full.assert_called_once_with(event)
        home.assert_called_once_with(event)
        self.view.open_event_editor.assert_not_called()
        self.widget.edit.assert_not_called()
        element = Mock()
        self.view.bind_event_drag(element, event)
        element.props.assert_not_called()

    async def test_manual_refresh_and_inactive_timers(self):
        for target in (self.view, self.widget):
            target.reload = AsyncMock()
            await target.force_reload()
            target.reload.assert_awaited_once_with(force=True)
            target.reload.reset_mock()
            target.calendars = self.repo.calendars()
            await target.refresh_google()
            target.reload.assert_awaited_once_with(force=True)
            target.reload.reset_mock()
        self.db.lock()
        for target in (self.view, self.widget):
            await target.refresh_google()
            await target.refresh_if_changed()
            target.reload.assert_not_called()

    async def test_deleted_screens_do_not_refresh(self):
        self.view.grid.is_deleted = self.widget.body.is_deleted = True
        for target in (self.view, self.widget):
            target.reload = AsyncMock()
            await target.refresh_google()
            await target.refresh_if_changed()
            target.reload.assert_not_called()

    async def test_hidden_screens_do_not_refresh(self):
        for target in (self.view, self.widget):
            target.is_active = lambda: False
            target.reload = AsyncMock()
            await target.refresh_google()
            await target.refresh_if_changed()
            target.reload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
