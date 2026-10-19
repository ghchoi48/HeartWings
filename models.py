"""UI나 DB 드라이버에 의존하지 않는 입력 및 저장 데이터 모델."""

from datetime import date, datetime
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class InputModel(BaseModel):
    """입력을 검증하며 생성 후 변경을 금지한다. 수정 시 새 모델을 생성한다."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, frozen=True)


class StudentInput(InputModel):
    """학적 식별 번호는 선택 사항이며 이름은 중복을 허용한다."""

    name: str = Field(min_length=1, max_length=100)
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


class Student(StudentInput, FamilyInput):
    """DB에서 읽은 학생과 UTC 생성/수정 시각."""

    id: int
    created_at: datetime
    updated_at: datetime

    @field_validator('family_members', mode='before')
    @classmethod
    def decode_family_members(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class CounselingInput(InputModel):
    """상담 예약과 일지를 함께 표현한다. 시각에는 시간대가 필수다."""

    student_id: int = Field(gt=0)
    starts_at: datetime
    duration_minutes: int = Field(default=50, ge=1, le=1440)
    category: str = Field(default='개인상담', min_length=1, max_length=100)
    status: Literal['scheduled', 'completed', 'cancelled'] = 'scheduled'
    title: str = Field(min_length=1, max_length=200)
    content_markdown: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default='', max_length=200000)
    follow_up: str = Field(default='', max_length=20000)

    @field_validator('starts_at')
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """운영체제별 로컬 시간 해석 차이를 방지한다."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('상담 시각에 시간대를 포함하세요.')
        return value


class Counseling(CounselingInput):
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
