"""상담기록관리 XLSB의 저장된 셀 값만 읽는다. 매크로/수식은 실행하지 않는다."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from zipfile import ZipFile
import hashlib
import json
import re

from pyxlsb import open_workbook, convert_date
from pydantic import ValidationError

from maeumnarae.core.models import (StudentInput, GroupCounselingInput, CounselingInput, GroupLogInput,
                    TeacherInput, ConsultationInput, CONSULTATION_AREAS, PsychologicalTestInput,
                    GUARDIAN_COUNSELING_AREAS, EducationEventInput)

MAX_BYTES = 10 * 1024 * 1024
PERSON_HEADERS = ['사례번호', '소속학교', '성명/집단명', '성별/인원', '학년', '반',
                  '생년월일', '학생연락처', '보호자연락처', '비고']
LOG_HEADERS = ['접수', '일자', '교시', '시간(시)', '시간(분)', '사례번호', '소속학교',
               '성명/집단명', '성별/인원', '회기', '대상', '상담인원', '상담매체',
               '대분류', '중분류', '상담구분', '학년도', '상담일자', '상담제목', '상담내용',
               '기관유형', '상담분류', '상담자구분', '상담자성명']


@dataclass(frozen=True)
class LegacyPerson:
    row: int
    key: str
    value: StudentInput | GroupCounselingInput | TeacherInput


@dataclass(frozen=True)
class LegacyLog:
    row: int
    key: str
    value: CounselingInput | GroupLogInput | ConsultationInput | PsychologicalTestInput | EducationEventInput
    author: str
    special_law: str = ''


@dataclass(frozen=True)
class LegacyBatch:
    people: tuple[LegacyPerson, ...]
    logs: tuple[LegacyLog, ...]
    errors: tuple[str, ...]
    fingerprint: str
    actions: tuple[tuple[str, str], ...] = ()


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def excel_day(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= 0:
            raise ValueError('날짜가 비어 있거나 올바르지 않습니다.')
        return convert_date(value).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(re.sub(r'[./]', '-', text(value)))


def original(row):
    return '\n'.join(f'{key}: {text(value)}' for key, value in row.items() if text(value))


def read_rows(content):
    if not content or len(content) > MAX_BYTES:
        raise ValueError('10MB 이하의 XLSB 파일을 선택하세요.')
    try:
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 512 or sum(i.file_size for i in archive.infolist()) > 80 * 1024 * 1024:
                raise ValueError('압축 해제 크기가 너무 큽니다.')
        result = {}
        with open_workbook(BytesIO(content)) as book:
            for name, required in [('인적사항등록', PERSON_HEADERS), ('상담대장', LOG_HEADERS)]:
                with book.get_sheet(name) as sheet:
                    if sheet.dimension.h > 20000 or sheet.dimension.w > 100:
                        raise ValueError('시트는 최대 20,000행, 100열까지 지원합니다.')
                    headers = None
                    records = []
                    for cells in sheet.rows(sparse=True):
                        number = cells[0].r + 1
                        if number > 20000 or len(cells) > 100:
                            raise ValueError('시트 크기 제한을 초과했습니다.')
                        if headers is None:
                            labels = [re.sub(r'\s+', '', text(c.v)) for c in cells]
                            if all(label in labels for label in required):
                                if any(labels.count(label) != 1 for label in required):
                                    raise ValueError(f'{name}: 중복된 제목 열입니다.')
                                headers = {label: labels.index(label) for label in required}
                            elif number > 20:
                                raise ValueError(f'{name}: 원본 서식의 제목 행을 찾지 못했습니다.')
                            continue
                        row = {key: cells[index].v if index < len(cells) else None for key, index in headers.items()}
                        # 빈 서식의 접수번호/학년도/날짜 계산값은 기록이 아니다.
                        meaningful = (PERSON_HEADERS if name == '인적사항등록' else
                                      [key for key in LOG_HEADERS if key not in ('접수', '학년도', '상담일자', '소속학교', '성별/인원')])
                        if any(text(row[key]) for key in meaningful):
                            records.append((number, row))
                    if headers is None:
                        raise ValueError(f'{name}: 원본 서식의 제목 행이 없습니다.')
                    result[name] = records
        return result
    except ValueError:
        raise
    except Exception:
        raise ValueError('XLSB 파일을 읽지 못했습니다. 두 시트와 파일 형식을 확인하세요.') from None


def period_key(value):
    """숫자 1, '01', '1교시'를 같은 교시로 취급한다."""
    label = re.sub(r'\s+', '', text(value))
    match = re.fullmatch(r'(\d+)(?:\.0+)?(?:교시)?', label)
    return str(int(match[1])) if match else label


def period_clocks(period_times):
    clocks = {}
    for label, value in (period_times or {}).items():
        key = period_key(label)
        if not key or not text(value):
            continue
        if key in clocks:
            raise ValueError(f'{key} 교시의 시작 시간이 중복되었습니다.')
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', text(value)):
            raise ValueError(f'{key} 교시 시작 시간을 HH:MM 형식으로 입력하세요.')
        clocks[key] = time.fromisoformat(text(value))
    return clocks


def duration_from_row(row):
    try:
        parts = [Decimal(text(row[key]) or '0') for key in ('시간(시)', '시간(분)')]
        if any(not part.is_finite() or part < 0 for part in parts) or parts[0] > 24 or parts[1] > 1440:
            raise ValueError
        total = parts[0] * 60 + parts[1]
        if not 1 <= total <= 1440 or total != total.to_integral_value():
            raise ValueError
        return int(total)
    except (InvalidOperation, ValueError):
        raise ValueError('시간(시)·시간(분)은 음수가 아닌 숫자이며, 합계가 1~1440분의 정수여야 합니다.') from None


DESTINATIONS = ['개인 상담', '집단 상담', '교사 자문', '심리검사', '교육/행사', '특별교육']
SPECIAL_LAWS = ['학교폭력예방법', '교원지위법']


def destination(row, override=None):
    if override:
        if override not in DESTINATIONS:
            raise ValueError('등록할 일지를 선택하세요.')
        return override
    if text(row['대분류']) in ('교육', '연구', '의뢰'):
        return ''
    if (text(row['대분류']), text(row['중분류']), text(row['상담구분'])) == ('검사', '심리검사', '집단심리검사'):
        return '교육/행사'
    if text(row['상담구분']) == '개인심리검사':
        return '심리검사'
    if text(row['대분류']) in ('자문', '교원자문'):
        return '교사 자문'
    return '자동'


def parse_rows(rows, school_year, period_times=None, corrections=None, destinations=None, excluded=None, special_laws=None):
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    corrections, destinations, excluded = corrections or {}, destinations or {}, excluded or set()
    rows = {sheet: [(number, dict(row, **corrections.get((sheet, number), {})))
                    for number, row in records if (sheet, number) not in excluded]
            for sheet, records in rows.items()}
    if isinstance(school_year, bool) or int(school_year) != school_year or not 1900 <= school_year <= 9999:
        raise ValueError('학년도는 1900~9999 사이 정수여야 합니다.')
    special_laws = special_laws or {}
    clocks = period_clocks(period_times)
    people, logs, errors, identities = [], [], [], {}
    consultation_keys = {text(row['사례번호']) for number, row in rows['상담대장']
                         if destination(row, destinations.get(number)) == '교사 자문'}
    counseling_keys = {text(row['사례번호']) for number, row in rows['상담대장']
                       if destination(row, destinations.get(number)) not in ('교사 자문', '교육/행사', '')}
    for number, row in rows['인적사항등록']:
        try:
            key, name, gender = (text(row[k]) for k in ('사례번호', '성명/집단명', '성별/인원'))
            if not key or not name:
                raise ValueError('사례번호와 성명/집단명이 필요합니다.')
            notes = text(row['비고'])
            if key in consultation_keys:
                if key in counseling_keys:
                    raise ValueError('같은 사례번호에 교사 자문과 학생/집단 상담이 혼재합니다. 사례번호를 분리하세요.')
                value = TeacherInput(name=name, contact=text(row['학생연락처']))
            elif gender in ('남', '여', '남자', '여자', '기타'):
                value = StudentInput(name=name, gender={'남자': '남', '여자': '여'}.get(gender, gender),
                    school_year=int(school_year), grade=text(row['학년']), classroom=text(row['반']),
                    birth_date=excel_day(row['생년월일']) if text(row['생년월일']) else None,
                    student_contact=text(row['학생연락처']), guardian_contact=text(row['보호자연락처']), notes=notes)
            elif gender.isdigit() and int(gender) > 0:
                value = GroupCounselingInput(name=name, participants=f'원본 인원: {gender}명', notes=notes)
            else:
                raise ValueError('성별(남/여/기타) 또는 집단 인원(양의 정수)을 확인하세요.')
            if key in identities:
                if identities[key] == value:
                    continue
                raise ValueError('같은 사례번호의 인적사항이 서로 다릅니다.')
            identities[key] = value
            people.append(LegacyPerson(number, key, value))
        except (ValueError, TypeError, OverflowError) as error:
            message = '필수값·형식·길이를 확인하세요.' if isinstance(error, ValidationError) else str(error)
            errors.append(f'인적사항등록 {number}행: {message}')
    for number, row in rows['상담대장']:
        try:
            route = destination(row, destinations.get(number))
            if not route:
                raise ValueError('교육·연구·의뢰는 등록할 일지를 직접 선택하세요.')
            key = text(row['사례번호'])
            person = identities.get(key)
            if person is None and route != '교육/행사':
                raise ValueError('인적사항등록에 연결할 사례번호가 없습니다.')
            if person is not None and text(row['성명/집단명']) and text(row['성명/집단명']) != person.name:
                raise ValueError('사례번호의 성명/집단명이 일치하지 않습니다.')
            day = excel_day(row['일자'] if text(row['일자']) else row['상담일자'])
            period = period_key(row['교시'])
            if not period:
                raise ValueError('교시가 비어 있습니다.')
            if period not in clocks:
                raise ValueError(f'{period} 교시의 시작 시간을 설정하세요.')
            clock = clocks[period]
            duration_minutes = duration_from_row(row)
            starts = datetime.combine(day, clock, timezone(timedelta(hours=9)))
            body = '<p>' + escape(text(row['상담내용'])).replace('\n', '<br>') + '</p>'
            common = dict(starts_at=starts, duration_minutes=int(duration_minutes), status='completed',
                          title=text(row['상담제목']) or '이관 상담 기록')
            if route == '교육/행사':
                count = text(row['상담인원']) or text(row['성별/인원'])
                value = EducationEventInput(title=common['title'], event_date=day,
                    event_time=clock.strftime('%H:%M'), duration_minutes=duration_minutes,
                    category='단체심리검사' if text(row['상담구분']) == '집단심리검사' else '교육',
                    audience=text(row['대상']), participant_count=int(count) if count.isdigit() else None,
                    facilitator=text(row['상담자성명']), content=body, content_format='html')
            elif route == '심리검사':
                if not isinstance(person, StudentInput):
                    raise ValueError('개인심리검사는 학생 인적사항에 연결해야 합니다.')
                value = PsychologicalTestInput(student_id=1, title=common['title'],
                    test_date=day, test_time=clock.strftime('%H:%M'), duration_minutes=duration_minutes,
                    target='보호자(학부모)' if text(row['대상']) in ('학부모', '보호자', '보호자(가족)', '보호자(학부모)') else '학생',
                    content=body, content_format='html')
            elif route == '교사 자문':
                area = text(row['상담구분'])
                if area and area not in CONSULTATION_AREAS:
                    raise ValueError('상담구분을 자문분야(학교학습·사회성발달·정서발달·진로발달·행동발달·기타)로 수정하세요.')
                value = ConsultationInput(teacher_id=1, **common,
                    consultation_area=area if area in CONSULTATION_AREAS else '',
                    content_html=body)
            elif route in ('개인 상담', '특별교육') or (route == '자동' and isinstance(person, StudentInput)):
                if not isinstance(person, StudentInput):
                    raise ValueError(f'{route}은 학생 인적사항에 연결해야 합니다.')
                if route == '특별교육' and special_laws.get(number) not in SPECIAL_LAWS:
                    raise ValueError('특별교육의 근거 법률을 선택하세요.')
                guardian = text(row['중분류']) == '학부모상담'
                area = text(row['상담구분'])
                if guardian and area not in GUARDIAN_COUNSELING_AREAS:
                    area = '기타'
                value = CounselingInput(student_id=1, **common, content_format='html', content_markdown=body,
                    category=text(row['중분류']) or '개인상담', counseling_method=text(row['상담매체']),
                    counseling_target='보호자(가족)' if guardian else text(row['대상']), counseling_area=area)
            else:
                if not isinstance(person, GroupCounselingInput):
                    raise ValueError('집단 상담은 집단 인적사항에 연결해야 합니다.')
                value = GroupLogInput(group_id=1, **common, content_html=body)
            logs.append(LegacyLog(number, key, value, text(row['상담자성명']),
                                  special_laws[number] if route == '특별교육' else ''))
        except (ValueError, TypeError, OverflowError) as error:
            message = '필수값·날짜·길이를 확인하세요.' if isinstance(error, ValidationError) else str(error)
            errors.append(f'상담대장 {number}행: {message}')
    if not people and not logs and not errors:
        errors.append('입력된 인적사항과 상담 기록이 없습니다. 빈 서식은 가져오지 않습니다.')
    return LegacyBatch(tuple(people), tuple(logs), tuple(errors), fingerprint)


def parse_legacy(content, school_year, period_times=None, **options):
    return parse_rows(read_rows(content), school_year, period_times, **options)
