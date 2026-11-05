"""Bounded, read-only ICS downloads with an encrypted last-good snapshot."""
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from math import ceil
import ssl
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, build_opener
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from maeumnarae.core.models import CalendarEvent
from maeumnarae.repositories.google_calendar_repo import GoogleCalendarRepository, validate_url
from maeumnarae.services.reporting import KST
from maeumnarae.services.tls import ssl_context

REFRESH_SECONDS = 900
MAX_BYTES = 5_000_000
_locks = WeakKeyDictionary()
_guard = Lock()


class GoogleCalendarError(ValueError):
    """Sanitized message safe to show in the UI."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GoogleCalendarError('캘린더 주소가 변경되었습니다. 비공개 주소를 다시 확인해 주세요.')


def parse_calendar(raw):
    try:
        calendar = icalendar.Calendar.from_ical(raw)
        if calendar.name != 'VCALENDAR' or calendar.get('VERSION') != '2.0':
            raise ValueError
        for event in calendar.walk('VEVENT'):
            if event.errors or not event.get('UID') or not event.get('DTSTART'):
                raise ValueError
        return calendar
    except Exception:
        raise GoogleCalendarError('캘린더 응답을 읽지 못했습니다. 비공개 주소를 확인하고 새로고침해 주세요.') from None


def download(url):
    url = validate_url(url)
    try:
        opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl_context()))
        deadline = monotonic() + 20
        with opener.open(url, timeout=10) as response:
            chunks, size = [], 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES or monotonic() > deadline:
                    raise GoogleCalendarError('캘린더 응답이 너무 크거나 오래 걸립니다. 잠시 후 새로고침해 주세요.')
                chunks.append(chunk)
        raw = b''.join(chunks)
        parse_calendar(raw)
        return raw
    except GoogleCalendarError:
        raise
    except HTTPError as error:
        raise GoogleCalendarError(f'구글 캘린더 요청이 거부되었습니다 (HTTP {error.code}). 비공개 주소를 확인하고 다시 시도해 주세요.') from None
    except (ssl.SSLError, URLError) as error:
        reason = getattr(error, 'reason', error)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise GoogleCalendarError('구글 캘린더의 HTTPS 인증서를 검증하지 못했습니다. 운영체제의 신뢰할 수 있는 인증서와 기관 보안 프로그램 설정을 확인해 주세요.') from None
        if isinstance(reason, ssl.SSLError):
            raise GoogleCalendarError('구글 캘린더와 보안 연결(TLS)을 맺지 못했습니다. 네트워크 보안 설정을 확인해 주세요.') from None
        raise GoogleCalendarError('구글 캘린더에 연결하지 못했습니다. 인터넷과 비공개 주소를 확인하고 새로고침해 주세요.') from None
    except Exception:
        raise GoogleCalendarError('구글 캘린더에 연결하지 못했습니다. 인터넷과 비공개 주소를 확인하고 새로고침해 주세요.') from None


def events_from_ics(raw, row, start: date, end: date):
    try:
        calendar = parse_calendar(raw)
        zone = ZoneInfo(str(calendar.get('X-WR-TIMEZONE', 'Asia/Seoul')))
        # The recurrence library normalizes every floating value, including EXDATE/RDATE.
        if not calendar.get('X-WR-TIMEZONE'):
            calendar.add('X-WR-TIMEZONE', 'Asia/Seoul')
        begins = datetime.combine(start, time.min, KST)
        ends = datetime.combine(end + timedelta(days=1), time.min, KST)
        result = {}
        # Padding includes all-day dates regardless of the feed's timezone.
        occurrences = recurring_ical_events.of(calendar).between(begins - timedelta(days=1), ends + timedelta(days=1))
        for event in occurrences:
            if str(event.get('STATUS', '')).upper() == 'CANCELLED':
                continue
            dt = event.decoded('DTSTART')
            all_day = not isinstance(dt, datetime)
            first = datetime.combine(dt, time.min, KST) if all_day else dt.replace(tzinfo=zone) if dt.tzinfo is None else dt
            stop = event.decoded('DTEND', None)
            if stop is None:
                stop = first + event.decoded('DURATION', timedelta(days=1) if all_day else timedelta(minutes=1))
            elif not isinstance(stop, datetime):
                stop = datetime.combine(stop, time.min, KST)
            elif stop.tzinfo is None:
                stop = stop.replace(tzinfo=zone)
            first, stop = first.astimezone(KST), stop.astimezone(KST)
            if stop < first:
                raise ValueError
            stop = max(stop, first + timedelta(minutes=1))
            if first >= ends or stop <= begins:
                continue
            identity = f"{event.get('UID')}|{event.decoded('RECURRENCE-ID', dt)}"
            entry_id = int.from_bytes(sha256(identity.encode()).digest()[:8], 'big')
            result[identity] = CalendarEvent(
                id=entry_id, calendar_id=-(row['id'] + 2), source='google_ics',
                calendar_name=row['name'], color=row['color'],
                title=str(event.get('SUMMARY') or '(제목 없음)')[:200],
                starts_at=first, duration_minutes=max(1, ceil((stop - first).total_seconds() / 60)),
                all_day=all_day, location=str(event.get('LOCATION', ''))[:200],
                content=str(event.get('DESCRIPTION', ''))[:20000])
        return sorted(result.values(), key=lambda e: (e.starts_at, e.id))
    except GoogleCalendarError:
        raise
    except Exception:
        raise GoogleCalendarError('캘린더 일정 형식을 읽지 못했습니다. 비공개 주소를 확인하고 새로고침해 주세요.') from None


def load_google_events(database, calendars, start, end, force=False):
    repository = GoogleCalendarRepository(database)
    ids = {-c.id - 2 for c in calendars if c.source == 'google_ics' and c.visible}
    result, messages = [], []
    requested_at = datetime.now(timezone.utc)
    for subscription_id in sorted(ids):
        with _guard:
            lock = _locks.setdefault(database._state, {}).setdefault(subscription_id, Lock())
        with lock:
            row = repository.get(subscription_id)
            if not row or not row['visible']:
                continue
            checked = datetime.fromisoformat(row['checked_at']) if row['checked_at'] else None
            due = checked is None or (requested_at - checked).total_seconds() >= REFRESH_SECONDS
            if due or (force and checked < requested_at):
                try:
                    raw = download(row['url'])
                    events_from_ics(raw, row, start, end)
                    repository.store_result(row, datetime.now(timezone.utc).isoformat(), ics=raw)
                except GoogleCalendarError as error:
                    repository.store_result(row, datetime.now(timezone.utc).isoformat(), error=str(error))
                current = repository.get(subscription_id)
                if not current or current['revision'] != row['revision'] or not current['visible']:
                    continue
                row = current
            if row['ics'] is not None:
                try:
                    result.extend(events_from_ics(row['ics'], row, start, end))
                except GoogleCalendarError as error:
                    messages.append(f"{row['name']}: {error}")
            last = datetime.fromisoformat(row['fetched_at']).astimezone(KST).strftime('%m/%d %H:%M') if row['fetched_at'] else '없음'
            messages.append(f"{row['name']} · 마지막 갱신 {last}" + (f" · {row['error']} (마지막 정상 일정 표시)" if row['error'] else ''))
    return result, ' · '.join(messages)
