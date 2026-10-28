"""PDF 요청과 읽기 전용 출력 데이터. DB/UI 의존성이 없다."""
from dataclasses import dataclass
from datetime import date, datetime

KINDS = {'individual': '개인상담', 'group': '집단상담', 'special': '특별교육',
         'consultation': '자문', 'test': '심리검사', 'education': '교육/행사'}
STATUSES = {'completed': '완료', 'scheduled': '예약', 'cancelled': '취소'}


@dataclass(frozen=True)
class PrintRequest:
    refs: tuple[tuple[str, int], ...] = ()
    school_year: int | None = None
    statuses: tuple[str, ...] = ('completed',)
    mask_names: bool = False

    def validate(self):
        if (self.school_year is None) == (not self.refs):
            raise ValueError('학년도 또는 출력할 일지를 선택하세요.')
        if self.school_year is not None and not 1900 <= self.school_year <= 9998:
            raise ValueError('학년도를 확인하세요.')
        if any(kind not in KINDS or not isinstance(key, int) or key <= 0 for kind, key in self.refs):
            raise ValueError('일지 선택을 확인하세요.')
        if not set(self.statuses) <= STATUSES.keys():
            raise ValueError('일지 상태를 확인하세요.')

    @property
    def bounds(self):
        return (date(self.school_year, 3, 1), date(self.school_year + 1, 3, 1))


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
