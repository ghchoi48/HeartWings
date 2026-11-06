"""나이스 학교기본정보·급식식단정보 API. 인증키와 원문 오류는 로그에 남기지 않는다."""

import json
import re
import ssl

import certifi
from datetime import date
from html import unescape
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

OFFICES = {
    'B10': '서울특별시교육청', 'C10': '부산광역시교육청', 'D10': '대구광역시교육청',
    'E10': '인천광역시교육청', 'F10': '광주광역시교육청', 'G10': '대전광역시교육청',
    'H10': '울산광역시교육청', 'I10': '세종특별자치시교육청', 'J10': '경기도교육청',
    'K10': '강원특별자치도교육청', 'M10': '충청북도교육청', 'N10': '충청남도교육청',
    'P10': '전북특별자치도교육청', 'Q10': '전라남도교육청', 'R10': '경상북도교육청',
    'S10': '경상남도교육청', 'T10': '제주특별자치도교육청',
}
MEALS = {'1': '아침', '2': '점심', '3': '저녁'}
SOURCE_URL = 'https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN17320190722180924242823&infSeq=2'


class NeisError(RuntimeError):
    """사용자에게 표시할 수 있는 조회 오류."""


def request_rows(service: str, parameters: dict, api_key: str = '') -> list[dict]:
    params = {'Type': 'json', 'pIndex': 1, 'pSize': 100, **parameters}
    if api_key:
        params['KEY'] = api_key
    url = f'https://open.neis.go.kr/hub/{service}?{urlencode(params)}'
    try:
        with urlopen(url, timeout=10, context=ssl.create_default_context(cafile=certifi.where())) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('response too large')
        payload = json.loads(raw.decode('utf-8-sig'))
        results = [payload['RESULT']] if 'RESULT' in payload else []
        sections = payload.get(service, [])
        for section in sections:
            results.extend(head['RESULT'] for head in section.get('head', []) if 'RESULT' in head)
        for result in results:
            code = result.get('CODE')
            if code == 'INFO-200':
                return []
            if code != 'INFO-000':
                if code == 'ERROR-290':
                    raise NeisError('나이스 인증키를 확인해 주세요. 설정의 학교 정보에서 변경할 수 있습니다.')
                raise NeisError('나이스 조회를 처리하지 못했습니다. 설정과 인증키 사용량을 확인한 뒤 다시 시도해 주세요.')
        rows = [row for section in sections for row in section.get('row', [])]
        if not sections or any(not isinstance(row, dict) for row in rows):
            raise ValueError('invalid response')
        return rows
    except (URLError, TimeoutError, OSError):
        raise NeisError('나이스에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.') from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise NeisError('나이스 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.') from None


def find_schools(office: str, name: str, api_key: str = '') -> list[dict]:
    if office not in OFFICES or not name.strip():
        raise NeisError('학교명과 시도교육청을 먼저 입력해 주세요.')
    return request_rows('schoolInfo', {'ATPT_OFCDC_SC_CODE': office, 'SCHUL_NM': name.strip()}, api_key)


def fetch_meals(office: str, school_code: str, day: date, meal: str, api_key: str = '') -> list[dict]:
    if office not in OFFICES or not re.fullmatch(r'[0-9]{7}', school_code) or meal not in MEALS:
        raise NeisError('설정 → 학교 정보에서 시도교육청과 나이스 학교 코드를 입력해 주세요.')
    rows = request_rows('mealServiceDietInfo', {
        'ATPT_OFCDC_SC_CODE': office, 'SD_SCHUL_CODE': school_code,
        'MLSV_YMD': day.strftime('%Y%m%d'), 'MMEAL_SC_CODE': meal,
    }, api_key)
    return [row for row in rows if str(row.get('MMEAL_SC_CODE')) == meal
            and row.get('MLSV_YMD') == day.strftime('%Y%m%d')
            and str(row.get('SD_SCHUL_CODE')) == school_code
            and row.get('ATPT_OFCDC_SC_CODE') == office]


def text_lines(value: str) -> list[str]:
    """줄바꿈만 보존하고 외부 HTML을 텍스트로 표시한다. 알레르기 번호는 유지한다."""
    text = re.sub(r'<br\s*/?>', '\n', value or '', flags=re.I)
    text = unescape(re.sub(r'<[^>]*>', '', text))
    return [line.strip() for line in text.splitlines() if line.strip()]


def fetch_school_schedule(office: str, school_code: str, start: date, end: date,
                          api_key: str = '') -> list[dict]:
    """표시 기간의 학사일정을 페이지 누락 없이 조회한다."""
    if office not in OFFICES or not re.fullmatch(r'[0-9]{7}', school_code):
        raise NeisError('설정 → 일반 → 나이스 연동에서 시도교육청과 학교 코드를 확인해 주세요.')
    if not api_key.strip():
        raise NeisError('설정 → 일반 → 나이스 연동에 NEIS API 인증키를 입력해 주세요.')
    if start > end:
        raise NeisError('학사일정 조회 기간을 확인해 주세요.')
    rows = []
    for page in range(1, 101):
        batch = request_rows('SchoolSchedule', {
            'ATPT_OFCDC_SC_CODE': office, 'SD_SCHUL_CODE': school_code,
            'AA_FROM_YMD': start.strftime('%Y%m%d'), 'AA_TO_YMD': end.strftime('%Y%m%d'),
            'pIndex': page, 'pSize': 100,
        }, api_key)
        rows.extend(row for row in batch
                    if row.get('ATPT_OFCDC_SC_CODE') == office
                    and str(row.get('SD_SCHUL_CODE')) == school_code
                    and start.strftime('%Y%m%d') <= str(row.get('AA_YMD', '')) <= end.strftime('%Y%m%d'))
        if len(batch) < 100:
            return rows
    raise NeisError('학사일정 조회량이 너무 많습니다. 주간 보기로 다시 조회해 주세요.')
