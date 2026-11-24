"""나이스 학사일정을 읽기 전용 캘린더 일정으로 변환한다."""
from contextlib import nullcontext
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from weakref import WeakKeyDictionary

from maeumnarae.core.models import CalendarEvent
from maeumnarae.repositories.calendar.school_calendar_repo import SchoolCalendarRepository
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository
from maeumnarae.services.school.neis import NeisError, fetch_school_schedule, text_lines
from maeumnarae.services.reports.reporting import KST

NEIS_CALENDAR_ID = -2
NEIS_COLOR = '#7c3aed'
NEIS_NAME = '학사일정 (NEIS)'
SOURCE_URL = ('https://open.neis.go.kr/portal/data/service/selectServicePage.do'
              '?infId=OPEN17220190722175038389180&infSeq=2')


REFRESH_SECONDS = 900
_locks = WeakKeyDictionary()
_guard = Lock()


def load_school_events(database, calendars, start, end, force=False, *, cache_only=False):
    """Render the last good snapshot immediately, then refresh without losing it on errors."""
    if not any(c.source == 'neis' and c.visible for c in calendars):
        return [], ''
    repository = SchoolCalendarRepository(database)
    requested_at = datetime.now(timezone.utc)
    with _guard:
        lock = _locks.setdefault(database._state, Lock())
    # Reading cached data never waits for the remote request lock.
    with nullcontext() if cache_only else lock:
        settings = SchoolSettingsRepository(database).get()
        events, checked = repository.get(settings.neis_office_code, settings.neis_school_code, start, end)
        if cache_only:
            return events, ''
        checked = datetime.fromisoformat(checked) if checked else None
        due = checked is None or (requested_at - checked).total_seconds() >= REFRESH_SECONDS
        if not due and not (force and checked < requested_at):
            return events, ''
        try:
            rows = fetch_school_schedule(settings.neis_office_code, settings.neis_school_code,
                                         start, end, settings.neis_api_key)
            refreshed = events_from_rows(rows)
            if not repository.store(settings, start, end, refreshed, datetime.now(timezone.utc).isoformat()):
                return [], ''
            return refreshed, '' if refreshed else '해당 기간에 등록된 나이스 학사일정이 없습니다.'
        except NeisError as error:
            message = str(error)
        except (ValueError, TypeError, AttributeError):
            message = '나이스 학사일정 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.'
        if SchoolSettingsRepository(database).get() != settings:
            return [], ''
        return events, message + (' (마지막 정상 일정 표시)' if events else '')


def events_from_rows(rows):
    events = []
    seen = set()
    for row in rows:
        day = datetime.strptime(str(row.get('AA_YMD', '')), '%Y%m%d').replace(tzinfo=KST)
        title = ' '.join(text_lines(str(row.get('EVENT_NM') or '학사일정')))[:200]
        content = '\n'.join(text_lines(str(row.get('EVENT_CNTNT') or '')))
        grades = [str(i) for i, key in enumerate(('ONE', 'TW', 'THREE', 'FR', 'FIV', 'SIX'), 1)
                  if row.get(f'{key}_GRADE_EVENT_YN') == 'Y']
        if grades:
            content += '\n대상 학년: ' + ', '.join(grades) + '학년'
        identity = (day.isoformat(), title, content)
        if identity in seen:
            continue
        seen.add(identity)
        entry_id = int.from_bytes(sha256(repr(identity).encode()).digest()[:8], 'big')
        events.append(CalendarEvent(id=entry_id, calendar_id=NEIS_CALENDAR_ID,
            title=title or '학사일정', starts_at=day, duration_minutes=1440, all_day=True,
            content=content[:20000], source='neis', calendar_name=NEIS_NAME, color=NEIS_COLOR,
            display_name=title))
    return sorted(events, key=lambda event: (event.starts_at, event.id))
