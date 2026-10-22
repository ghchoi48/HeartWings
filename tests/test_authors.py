"""실제 SQLCipher에서 작성자 스냅샷, 수정 및 구버전 마이그레이션 검증."""

from datetime import datetime, timezone

import pytest

from database import Database, SCHEMA_VERSION
from models import (
    CalendarInput, CalendarEventInput, CounselingInput, CounselingCaseInput,
    ConsultationInput, EducationEventInput, GroupCounselingInput, GroupLogInput,
    PsychologicalTestInput, SchoolSettings, SpecialEducationInput, StudentInput, TeacherInput,
)
from repositories.calendar_repo import CalendarRepository
from repositories.case_repo import CaseRepository
from repositories.consultation_repo import ConsultationRepository
from repositories.counseling_repo import CounselingRepository
from repositories.education_event_repo import EducationEventRepository
from repositories.group_counseling_repo import GroupCounselingRepository
from repositories.psychological_test_repo import PsychologicalTestRepository
from repositories.school_settings_repo import SchoolSettingsRepository
from repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from repositories.student_repo import StudentRepository
from repositories.teacher_repo import TeacherRepository


@pytest.fixture
def db(tmp_path):
    database = Database('author-test', tmp_path / 'authors.db')
    database.initialize(SchoolSettings(counselor_name='첫 상담교사'))
    return database


def tables(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def test_all_records_snapshot_author_and_preserve_it_on_edit(db):
    students = StudentRepository(db)
    student = students.create(StudentInput(name='학생', grade=1, classroom='1'))
    teacher = TeacherRepository(db).save(TeacherInput(name='담임'))
    group_value = GroupCounselingInput(name='집단', student_ids=[student.id])
    groups = GroupCounselingRepository(db)
    group = groups.save(group_value)
    special = SpecialEducationRepository(db).save(SpecialEducationInput(
        student_id=student.id, title='특별교육', law='교원지위법'))
    calendars = CalendarRepository(db)
    calendar = calendars.create(CalendarInput(name='일정'))
    now = datetime(2026, 10, 22, 3, tzinfo=timezone.utc)
    day = now.date()
    counseling_value = CounselingInput(student_id=student.id, title='상담', starts_at=now)
    records = [student, teacher, group, special, calendar]
    # 동일 입력으로 생성/수정하여 모든 업무 기록의 작성자 유지 여부를 확인한다.
    saves = [
        (CounselingRepository(db).create, CounselingRepository(db).update, counseling_value),
        (lambda value: CaseRepository(db).save(value),
         lambda entry_id, value: CaseRepository(db).save(value, entry_id),
         CounselingCaseInput(student_id=student.id, title='사례')),
        (lambda value: ConsultationRepository(db).save(value),
         lambda entry_id, value: ConsultationRepository(db).save(value, entry_id),
         ConsultationInput(teacher_id=teacher.id, title='자문', starts_at=now)),
        (lambda value: groups.save_log(value), lambda entry_id, value: groups.save_log(value, entry_id),
         GroupLogInput(group_id=group.id, title='집단 일지', starts_at=now)),
        (SpecialEducationLogRepository(db).create, SpecialEducationLogRepository(db).update,
         counseling_value.model_copy(update={'case_id': special.id})),
        (lambda value: EducationEventRepository(db).save(value),
         lambda entry_id, value: EducationEventRepository(db).save(value, entry_id),
         EducationEventInput(title='교육', event_date=day)),
        (lambda value: PsychologicalTestRepository(db).save(value),
         lambda entry_id, value: PsychologicalTestRepository(db).save(value, entry_id),
         PsychologicalTestInput(student_id=student.id, title='검사', test_date=day)),
    ]
    entries = [(create(value), update, value) for create, update, value in saves]
    records.extend(entry for entry, _, _ in entries)
    assert all(record.author == '첫 상담교사' for record in records)
    event_value = CalendarEventInput(calendar_id=calendar.id, title='일정', starts_at=now)
    calendars.save_event(event_value)
    with db.session(write=True) as connection:
        connection.execute("INSERT INTO home_preferences (id, layout) VALUES (1, '[]')")
        connection.execute("INSERT INTO home_todos (title) VALUES ('할 일')")
        original = {table: [dict(row) for row in connection.execute(f'SELECT rowid, author FROM "{table}"')]
                    for table in tables(connection)}
        assert all(rows and all(row['author'] == '첫 상담교사' for row in rows)
                   for rows in original.values())
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='새 상담교사'))
    for entry, update, value in entries:
        assert update(entry.id, value).author == '첫 상담교사'
    assert students.update(student.id, StudentInput(name='수정', grade=2, classroom='2')).author == '첫 상담교사'
    assert TeacherRepository(db).save(TeacherInput(name='수정'), teacher.id).author == '첫 상담교사'
    assert groups.save(group_value, group.id).author == '첫 상담교사'
    assert SpecialEducationRepository(db).save(SpecialEducationInput(
        student_id=student.id, title='수정', law='교원지위법'), special.id).author == '첫 상담교사'
    event = next(event for event in calendars.events(day, day, [calendar.id]))
    assert event.author == '첫 상담교사'
    calendars.save_event(event_value, event.id)
    calendars.set_visible(calendar.id, False)
    db.initialize()
    with db.session() as connection:
        assert original == {table: [dict(row) for row in connection.execute(f'SELECT rowid, author FROM "{table}"')]
                            for table in tables(connection)}
    assert students.create(StudentInput(name='새 학생', grade=1, classroom='1')).author == '새 상담교사'
    assert CounselingRepository(db).create(counseling_value).author == '새 상담교사'


def test_version_26_migration_backfills_once(db):
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    with db.session(write=True) as connection:
        for table in tables(connection):
            connection.execute(f'DROP TRIGGER "{table}_snapshot_author"')
            connection.execute(f'ALTER TABLE "{table}" DROP COLUMN author')
        connection.execute('PRAGMA user_version=26')
    db.initialize()
    assert StudentRepository(db).get(student.id).author == '첫 상담교사'
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='새 상담교사'))
    reopened = Database('author-test', db.path)
    reopened.initialize()
    assert StudentRepository(reopened).get(student.id).author == '첫 상담교사'
    with reopened.session() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_missing_counselor_stays_blank_after_name_is_set(tmp_path):
    db = Database('author-test', tmp_path / 'blank.db')
    db.initialize()
    students = StudentRepository(db)
    student = students.create(StudentInput(name='학생', grade=1, classroom='1'))
    assert student.author == ''
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='새 상담교사'))
    db.initialize()
    assert students.get(student.id).author == ''
    assert students.create(StudentInput(name='새 학생', grade=1, classroom='1')).author == '새 상담교사'
