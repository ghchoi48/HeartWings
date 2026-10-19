"""실제 SQLCipher 집계, 한국 날짜 경계, 보고서 일관성과 달력 계산 검증."""

import csv
import io
from datetime import date, datetime

import pytest

from database import Database
from models import CounselingInput, StudentInput
from reporting import KST, date_bounds, report_csv, report_html
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository
from repositories.reporting_repo import ReportingRepository
from views.calendar_view import visible_days


@pytest.fixture
def setup(tmp_path):
    db = Database('report-test-only', tmp_path / 'report.db')
    db.initialize()
    students = StudentRepository(db)
    a = students.create(StudentInput(name='학생 A', grade=2, classroom='1'))
    b = students.create(StudentInput(name='학생 B', grade=3, classroom='2'))
    repo = CounselingRepository(db)
    for student, moment, status, duration, category in [
        (a, '2026-09-30T23:59:59.999999', 'completed', 99, '범위 밖'),
        (a, '2026-10-01T00:00:00', 'completed', 30, '개인'),
        (a, '2026-10-15T13:00:00', 'completed', 50, '개인'),
        (b, '2026-10-31T23:59:59.999999', 'completed', 40, '=위험<html>'),
        (b, '2026-10-15T14:00:00', 'scheduled', 60, '예약'),
        (a, '2026-10-15T15:00:00', 'cancelled', 70, '취소'),
        (b, '2026-11-01T00:00:00', 'completed', 99, '범위 밖'),
    ]:
        repo.create(CounselingInput(student_id=student.id, title='비공개상담제목', content_markdown='비공개본문',
            starts_at=datetime.fromisoformat(moment).replace(tzinfo=KST), status=status,
            duration_minutes=duration, category=category))
    return db, ReportingRepository(db)


def test_statistics_kst_statuses_and_unique_students(setup):
    _, repo = setup
    report = repo.statistics(date(2026, 10, 1), date(2026, 10, 31))
    assert (report.total, report.completed, report.students, report.minutes) == (5, 3, 2, 120)
    assert {b.label: b.count for b in report.statuses} == dict(scheduled=1, completed=3, cancelled=1)
    assert {b.label: b.count for b in report.months} == {'2026-10': 3}
    assert {b.label: b.count for b in report.grades} == {'2': 2, '3': 1}
    counts = repo.daily_counts(date(2026, 10, 1), date(2026, 10, 31))
    assert counts == {date(2026, 10, 1): 1, date(2026, 10, 15): 3, date(2026, 10, 31): 1}
    assert sum(repo.daily_counts(date(2026, 10, 1), date(2026, 10, 31), 'completed').values()) == 3
    assert len(repo.day_items(date(2026, 10, 15), limit=1, offset=1)) == 1
    assert repo.day_items(date(2026, 10, 15), status='scheduled')[0].student_name == '학생 B'


def test_exports_and_empty_report(setup):
    _, repo = setup
    report = repo.statistics(date(2026, 10, 1), date(2026, 10, 31))
    data = report_csv(report)
    assert data.startswith(b'\xef\xbb\xbf')
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
    assert ['유형별 완료', "'=위험<html>", '1'] in rows
    html = report_html(report).decode()
    assert '=위험&lt;html&gt;' in html
    for private in ['학생 A', '학생 B', '비공개상담제목', '비공개본문']:
        assert private not in html and private not in data.decode('utf-8-sig')
    empty = repo.statistics(date(2025, 1, 1), date(2025, 1, 2))
    assert (empty.total, empty.completed, empty.students, empty.minutes) == (0, 0, 0, 0)
    assert empty.categories == ()


def test_no_thousand_row_truncation(setup):
    db, repo = setup
    with db.session(write=True) as connection:
        connection.executemany('''INSERT INTO counseling(student_id, case_id, starts_at, duration_minutes, category,
            status, title, content_markdown, follow_up, created_at, updated_at)
            VALUES(1, (SELECT id FROM counseling_cases WHERE student_id=1 LIMIT 1), '2026-10-19T15:00:00.000000+00:00', 1, '대량', 'completed', '테스트', '', '', '2026', '2026')''',
            [()] * 1005)
    report = repo.statistics(date(2026, 10, 20), date(2026, 10, 20))
    assert report.completed == report.total == report.minutes == 1005
    assert repo.daily_counts(date(2026, 10, 20), date(2026, 10, 20)) == {date(2026, 10, 20): 1005}


def test_date_validation_and_calendar_boundaries():
    with pytest.raises(ValueError):
        date_bounds(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        date_bounds(date.max, date.max)
    month = visible_days(date(2024, 2, 29), 'month')
    assert date(2024, 2, 29) in month and month[0].weekday() == 0 and len(month) % 7 == 0
    assert visible_days(date(2026, 1, 1), 'week')[0] == date(2025, 12, 29)
