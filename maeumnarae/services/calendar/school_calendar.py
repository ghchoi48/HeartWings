"""나이스 학사일정을 읽기 전용 캘린더 일정으로 변환한다."""
from datetime import datetime

from maeumnarae.core.models import CalendarEvent
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository
from maeumnarae.services.school.neis import NeisError, fetch_school_schedule, text_lines
from maeumnarae.services.reports.reporting import KST

NEIS_CALENDAR_ID = -2
NEIS_COLOR = '#7c3aed'
NEIS_NAME = '학사일정 (NEIS)'
SOURCE_URL = ('https://open.neis.go.kr/portal/data/service/selectServicePage.do'
              '?infId=OPEN17220190722175038389180&infSeq=2')


def load_school_events(database, calendars, start, end):
    """외부 조회 실패는 다른 캘린더를 가리지 않도록 별도 안내로 반환한다."""
    if not any(c.source == 'neis' and c.visible for c in calendars):
        return [], ''
    settings = SchoolSettingsRepository(database).get()
    try:
        rows = fetch_school_schedule(settings.neis_office_code, settings.neis_school_code,
                                     start, end, settings.neis_api_key)
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
            identity = (day, title, content)
            if identity in seen:
                continue
            seen.add(identity)
            events.append(CalendarEvent(id=len(events) + 1, calendar_id=NEIS_CALENDAR_ID,
                title=title or '학사일정', starts_at=day, duration_minutes=1440, all_day=True,
                content=content[:20000], source='neis', calendar_name=NEIS_NAME, color=NEIS_COLOR,
                display_name=title))
        return events, '' if events else '해당 기간에 등록된 나이스 학사일정이 없습니다.'
    except NeisError as error:
        return [], str(error)
    except (ValueError, TypeError):
        return [], '나이스 학사일정 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.'
