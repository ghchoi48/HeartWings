"""UI나 DB 드라이버에 의존하지 않는 입력 및 저장 데이터 모델."""

from datetime import date, datetime, timedelta, timezone
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class InputModel(BaseModel):
    """입력을 검증하며 생성 후 변경을 금지한다. 수정 시 새 모델을 생성한다."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, frozen=True)


class AuthoredRecord(InputModel):
    """생성 당시 상담교사 이름. 수정 입력 모델에는 포함하지 않는다."""

    author: str = ''


class SchoolSettings(InputModel):
    school_name: str = Field(default='', max_length=100)
    school_level: Literal['초등학교', '중학교', '고등학교'] = '중학교'
    counselor_name: str = Field(default='', max_length=100)
    office_number: str = Field(default='', max_length=50)
    neis_office_code: str = Field(default='', pattern=r'^(?:[B-HIJKMNPQRST]10)?$')
    neis_school_code: str = Field(default='', pattern=r'^(?:[0-9]{7})?$')
    neis_api_key: str = Field(default='', max_length=200)

    @property
    def grade_options(self) -> dict[int, str]:
        return {grade: f'{grade}학년' for grade in range(1, 7 if self.school_level == '초등학교' else 4)}


class TeacherInput(InputModel):
    """교사 연락처와 내선은 앞자리 0을 보존하는 문자열로 저장한다."""

    name: str = Field(min_length=1, max_length=100)
    contact: str = Field(default='', max_length=200)
    extension: str = Field(default='', max_length=50)
    responsibilities: str = Field(default='', max_length=200)


class Teacher(TeacherInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


CONSULTATION_AREAS = ['학교학습', '사회성발달', '정서발달', '진로발달', '행동발달', '기타']


class ConsultationInput(InputModel):
    teacher_id: int = Field(gt=0)
    consultation_area: Literal['', '학교학습', '사회성발달', '정서발달', '진로발달', '행동발달', '기타'] = ''
    starts_at: datetime
    duration_minutes: int = Field(default=30, ge=1, le=1440)
    status: Literal['scheduled', 'completed', 'cancelled'] = 'completed'
    title: str = Field(min_length=1, max_length=200)
    content_html: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    follow_up: str = Field(default='', max_length=20000)

    @field_validator('starts_at')
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('자문 시각에 시간대를 포함하세요.')
        return value


class Consultation(ConsultationInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


def current_school_year() -> int:
    today = datetime.now(timezone(timedelta(hours=9))).date()
    return today.year if today.month >= 3 else today.year - 1


class StudentEnrollmentInput(InputModel):
    school_year: int = Field(default_factory=current_school_year, ge=1900, le=9999)
    grade: int = Field(ge=1, le=12)
    classroom: str = Field(min_length=1, max_length=30)
    student_number: str | None = Field(default=None, min_length=1, max_length=50)


class StudentEnrollment(StudentEnrollmentInput, AuthoredRecord):
    student_id: int
    created_at: datetime
    updated_at: datetime


class StudentInput(InputModel):
    """학생 기본 정보와 한 학년도의 학적. 번호는 선택 사항이다."""

    name: str = Field(min_length=1, max_length=100)
    school_year: int = Field(default_factory=current_school_year, ge=1900, le=9999)
    nickname: str | None = Field(default='', max_length=100)
    student_number: str | None = Field(default=None, min_length=1, max_length=50)
    grade: int = Field(ge=1, le=12)
    classroom: str = Field(min_length=1, max_length=30)
    birth_date: date | None = None
    guardian_contact: str = Field(default='', max_length=200)
    student_contact: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=20000)


class FamilyMember(InputModel):
    """가족 구성원 한 명의 정보."""

    lives_together: bool = False
    relationship: str = Field(default='', max_length=100)
    name: str = Field(default='', max_length=100)
    age: int | None = Field(default=None, ge=0, le=150)
    occupation: str = Field(default='', max_length=200)
    contact: str = Field(default='', max_length=200)


class FamilyInput(InputModel):
    """학생의 가족 정보 수정 항목."""

    guardian_contact: str = Field(default='', max_length=200)
    family_type: str = Field(default='', max_length=200)
    family_welfare_type: str = Field(default='', max_length=200)
    family_members: list[FamilyMember] = Field(default_factory=list)


class Student(StudentInput, FamilyInput, AuthoredRecord):
    """DB에서 읽은 학생과 UTC 생성/수정 시각."""

    id: int
    created_at: datetime
    updated_at: datetime

    @field_validator('family_members', mode='before')
    @classmethod
    def decode_family_members(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class SpecialEducationInput(InputModel):
    student_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    law: Literal['학교폭력예방법', '교원지위법']
    case_number: str = Field(default='', max_length=100)


class SpecialEducation(SpecialEducationInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


class CounselingCaseInput(InputModel):
    """학생별 상담 사례와 HTML 사례 개념화 보고서."""

    student_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    report_html: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    intake_html: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    closing_html: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)


class CounselingCase(CounselingCaseInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


class CounselingInput(InputModel):
    """상담 예약과 일지를 함께 표현한다. 시각에는 시간대가 필수다."""

    student_id: int = Field(gt=0)
    case_id: int | None = Field(default=None, gt=0)
    starts_at: datetime
    duration_minutes: int = Field(default=50, ge=1, le=1440)
    category: str = Field(default='개인상담', min_length=1, max_length=100)
    counseling_method: str = Field(default='', max_length=100)
    counseling_target: str = Field(default='', max_length=200)
    counseling_area: str = Field(default='', max_length=100)
    status: Literal['scheduled', 'completed', 'cancelled'] = 'scheduled'
    title: str = Field(min_length=1, max_length=200)
    content_format: Literal['markdown', 'html'] = 'markdown'
    content_markdown: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    follow_up: str = Field(default='', max_length=20000)

    @field_validator('starts_at')
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """운영체제별 로컬 시간 해석 차이를 방지한다."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('상담 시각에 시간대를 포함하세요.')
        return value


class Counseling(CounselingInput, AuthoredRecord):
    """저장된 상담 일정/일지."""

    id: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ScheduleItem:
    """캘린더용 최소 정보. 상담 본문과 연락처는 조회하지 않는다."""

    id: int
    student_id: int
    student_name: str
    title: str
    starts_at: datetime
    duration_minutes: int
    status: str


@dataclass(frozen=True)
class ReportBucket:
    """통계 분류별 건수."""

    label: str
    count: int


@dataclass(frozen=True)
class CounselingReport:
    """한 트랜잭션에서 집계한 기간 통계. 완료 상담 기준 지표와 전체 상태 건수를 구분한다."""

    start: date
    end: date
    total: int
    completed: int
    students: int
    minutes: int
    statuses: tuple[ReportBucket, ...]
    categories: tuple[ReportBucket, ...]
    months: tuple[ReportBucket, ...]
    grades: tuple[ReportBucket, ...]


class GroupCounselingInput(InputModel):
    """집단 상담 프로그램의 기본 정보."""

    name: str = Field(min_length=1, max_length=200)
    facilitator: str = Field(default='', max_length=100)
    period: str = Field(default='', max_length=23)
    counseling_area: str = Field(default='', max_length=100)
    participants: str = Field(default='', max_length=20000)
    student_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)
    purpose: str = Field(default='', max_length=20000)
    notes: str = Field(default='', max_length=20000)

    @field_validator('period')
    @classmethod
    def validate_period(cls, value: str) -> str:
        if not value:
            return ''
        parts = value.split(' - ')
        if len(parts) not in (1, 2):
            raise ValueError('운영 기간은 날짜 또는 시작일 - 종료일 형식으로 입력하세요.')
        dates = [date.fromisoformat(part.strip()) for part in parts]
        if dates[0] > dates[-1]:
            raise ValueError('운영 종료일은 시작일보다 빠를 수 없습니다.')
        return ' - '.join(day.isoformat() for day in dates)


class GroupCounseling(GroupCounselingInput, AuthoredRecord):
    participant_labels: list[str] = Field(default_factory=list)
    id: int
    created_at: datetime
    updated_at: datetime


class GroupLogInput(InputModel):
    """집단에 종속되는 회기별 상담일지."""

    group_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    duration_minutes: int = Field(default=50, ge=1, le=1440)
    content_html: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    follow_up: str = Field(default='', max_length=20000)

    @field_validator('starts_at')
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('상담 시각에 시간대를 포함하세요.')
        return value


class GroupLog(GroupLogInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


class StudentTimelineEntry(BaseModel):
    """본문을 제외한 개인·집단 상담 및 특별교육 통합 이력."""

    id: int
    kind: Literal['individual', 'group', 'special_education'] = 'individual'
    education_name: str = ''
    starts_at: datetime
    duration_minutes: int
    title: str
    group_name: str = ''
    counseling_area: str = ''
    category: str = ''
    counseling_method: str = ''
    counseling_target: str = ''


class EducationEventInput(InputModel):
    title: str = Field(min_length=1, max_length=200)
    category: Literal['교육', '행사', '단체심리검사'] = '교육'
    event_date: date
    event_time: str = Field(default='', pattern=r'^$|^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    location: str = Field(default='', max_length=200)
    audience: str = Field(default='', max_length=200)
    facilitator: str = Field(default='', max_length=100)
    content: str = Field(default='', max_length=20000)
    content_format: Literal['text', 'html'] = 'text'


class EducationEvent(EducationEventInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


class PsychologicalTestInput(InputModel):
    student_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    test_date: date
    target: Literal['학생', '보호자(학부모)'] = '학생'
    test_time: str = Field(default='', pattern=r'^$|^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    content: str = Field(default='', max_length=20000)
    content_format: Literal['text', 'html'] = 'text'


class PsychologicalTest(PsychologicalTestInput, AuthoredRecord):
    id: int
    created_at: datetime
    updated_at: datetime


class CalendarInput(InputModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default='#0d9488', pattern=r'^#[0-9a-fA-F]{6}$')


class Calendar(CalendarInput, AuthoredRecord):
    id: int
    source: Literal['counseling', 'custom', 'holidays'] = 'custom'
    visible: bool = True


class CalendarEventInput(InputModel):
    calendar_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    status: Literal['scheduled', 'completed', 'cancelled'] = 'scheduled'

    @field_validator('starts_at')
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('시간대가 포함된 시각이 필요합니다.')
        return value


class CalendarEvent(CalendarEventInput, AuthoredRecord):
    id: int
    source: Literal['counseling', 'custom'] = 'custom'
    calendar_name: str
    color: str
    student_name: str = ''
