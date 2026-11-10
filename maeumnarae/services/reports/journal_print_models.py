"""PDF 요청과 읽기 전용 출력 데이터. DB/UI 의존성이 없다."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

KINDS = {'individual': '개인상담', 'group': '집단상담', 'special': '특별교육',
         'consultation': '자문', 'test': '심리검사', 'education': '교육/행사'}
STATUSES = {'completed': '완료', 'scheduled': '예약', 'cancelled': '취소'}


@dataclass(frozen=True)
class PrintRequest:
    refs: tuple[tuple[str, int], ...] = ()
    school_year: int | None = None
    statuses: tuple[str, ...] = ('completed',)
    mask_names: bool = False
    all_records: bool = False
    start_date: date | None = None
    end_date: date | None = None
    student_id: int | None = None

    def validate(self):
        has_period = self.start_date is not None or self.end_date is not None
        if sum((self.school_year is not None, bool(self.refs), self.all_records, has_period,
                self.student_id is not None)) != 1:
            raise ValueError('학년도 또는 출력할 일지를 선택하세요.')
        if self.student_id is not None and (type(self.student_id) is not int or self.student_id <= 0):
            raise ValueError('학생을 확인하세요.')
        if self.school_year is not None and (type(self.school_year) is not int or not 1900 <= self.school_year <= 9998):
            raise ValueError('학년도를 확인하세요.')
        if has_period and (type(self.start_date) is not date or type(self.end_date) is not date or
                           not date(1900, 1, 1) <= self.start_date <= self.end_date <= date(9998, 12, 31)):
            raise ValueError('시작일과 종료일을 확인하세요.')
        if any(kind not in KINDS or not isinstance(key, int) or key <= 0 for kind, key in self.refs):
            raise ValueError('일지 선택을 확인하세요.')
        if not set(self.statuses) <= STATUSES.keys():
            raise ValueError('일지 상태를 확인하세요.')

    @property
    def bounds(self):
        if self.start_date is not None:
            return self.start_date, self.end_date + timedelta(days=1)
        return (date(self.school_year, 3, 1), date(self.school_year + 1, 3, 1))

    @property
    def has_period(self):
        return self.school_year is not None or self.start_date is not None


@dataclass(frozen=True)
class PrintRecord:
    kind: str
    id: int
    subject_type: str
    subject_id: int
    subject: str
    moment: datetime
    title: str
    author: str
    status: str
    minutes: int | None
    content: str
    content_format: str
    follow_up: str = ''
    details: tuple[tuple[str, str], ...] = ()
    attendance: tuple[dict, ...] = ()
    enrollment_status: str = ''
    grade: int | None = None
    classroom: str = ''
    student_number: str = ''
    session_number: int | None = None
    participants: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class PrintSnapshot:
    school: str
    records: tuple[PrintRecord, ...]
    school_level: str = '중학교'

    @property
    def counts(self):
        return {kind: sum(r.kind == kind for r in self.records) for kind in KINDS}
