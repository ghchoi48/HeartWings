"""대한민국 공휴일과 대체공휴일 조회."""
from datetime import date
from functools import lru_cache

from holidays.countries.south_korea import SouthKorea

HOLIDAY_CALENDAR_ID = -1
HOLIDAY_COLOR = '#dc2626'


@lru_cache(maxsize=32)
def _year_holidays(year: int) -> tuple[tuple[date, str], ...]:
    return tuple(SouthKorea(years=[year], language='ko', observed=True).items())


def korean_holidays(start: date, end: date) -> dict[date, str]:
    return {day: name for year in range(start.year, end.year + 1)
            for day, name in _year_holidays(year) if start <= day <= end}


def is_day_off(day: date, holidays: dict[date, str]) -> bool:
    return day.weekday() >= 5 or day in holidays
