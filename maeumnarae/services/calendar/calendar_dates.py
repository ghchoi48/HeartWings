"""Shared calendar date calculations."""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from maeumnarae.services.reports.reporting import KST


def visible_days(anchor: date, mode: str) -> list[date]:
    """일요일 시작의 달력 날짜를 계산한다. 월간은 인접 월 날짜도 포함한다."""
    if mode == 'week':
        sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        return [sunday + timedelta(days=i) for i in range(7)]
    return [day for week in calendar.Calendar(firstweekday=6).monthdatescalendar(anchor.year, anchor.month) for day in week]


def event_dates(entry):
    begins = entry.starts_at.astimezone(KST)
    return begins.date(), (begins + timedelta(minutes=entry.duration_minutes) - timedelta(microseconds=1)).date()


def events_by_date(events, days):
    result = defaultdict(list)
    for entry in events:
        first, last = event_dates(entry)
        first, last = max(first, days[0]), min(last, days[-1])
        for offset in range((last - first).days + 1):
            result[first + timedelta(days=offset)].append(entry)
    return result


def shift_month(day, direction):
    month_index = day.year * 12 + day.month - 1 + direction
    year, month = divmod(month_index, 12)
    if not 2 <= year <= 9998:
        return day
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))
