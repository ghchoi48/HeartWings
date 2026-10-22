"""학년도 누적, 최신 학적 선택, 충돌 롤백 및 구버전 DB 이관."""

from datetime import datetime, timezone

import pytest

from database import ConflictError, Database, NotFoundError
from models import CounselingInput, SchoolSettings, StudentInput, StudentEnrollmentInput, current_school_year
from repositories.counseling_repo import CounselingRepository
from repositories.school_settings_repo import SchoolSettingsRepository
from repositories.student_repo import StudentRepository


@pytest.fixture
def db(tmp_path):
    database = Database('enrollment-test', tmp_path / 'students.db')
    database.initialize(SchoolSettings(counselor_name='첫 교사'))
    return database


def enrollment(year, grade=1, classroom='1', number='01'):
    return StudentEnrollmentInput(school_year=year, grade=grade, classroom=classroom, student_number=number)


def test_history_latest_year_and_immutable_authors(db):
    repo = StudentRepository(db)
    student = repo.create(StudentInput(name='학생', **enrollment(2025).model_dump()))
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='새 교사'))
    latest = repo.save_enrollment(student.id, enrollment(2026, 2, '3', '07'))
    repo.save_enrollment(student.id, enrollment(2024, 1, '2', '02'))
    assert repo.get(student.id).grade == 2
    assert repo.list(grade=2)[0].student_number == '07'
    assert not repo.list(grade=1)
    repo.save_enrollment(student.id, enrollment(2025, 1, '4', '09'))
    history = repo.enrollments(student.id)
    assert [row.school_year for row in history] == [2026, 2025, 2024]
    assert history[1].classroom == '4'
    assert history[1].author == '첫 교사'
    assert history[0].author == '새 교사'
    assert latest.author == student.author == '첫 교사'
    updated = repo.update(student.id, StudentInput(name='개명', **enrollment(2024, 1, '5').model_dump()))
    assert (updated.name, updated.school_year, updated.grade, updated.classroom) == ('개명', 2026, 2, '3')
    repo.delete(student.id)
    assert not repo.enrollments(student.id)


def test_scoped_number_conflict_rolls_back_student_and_history(db):
    repo = StudentRepository(db)
    first = repo.create(StudentInput(name='학생1', **enrollment(2026).model_dump()))
    second = repo.create(StudentInput(name='학생2', **enrollment(2026, classroom='2').model_dump()))
    repo.create(StudentInput(name='학생3', **enrollment(2025).model_dump()))
    revision = db.student_revision
    with pytest.raises(ConflictError):
        repo.update(second.id, StudentInput(name='덮어쓰기 금지', **enrollment(2026).model_dump()))
    assert repo.get(second.id) == second
    assert repo.enrollments(second.id)[0].classroom == '2'
    assert db.student_revision == revision
    assert repo.get(first.id) == first


def test_delete_enrollment_updates_latest_and_preserves_student_records(db):
    repo = StudentRepository(db)
    student = repo.create(StudentInput(name='학생', notes='메모', **enrollment(2024).model_dump()))
    repo.save_enrollment(student.id, enrollment(2025, 2, '2', '02'))
    latest = repo.save_enrollment(student.id, enrollment(2026, 3, '3', '03'))
    counseling = CounselingRepository(db).create(CounselingInput(
        student_id=student.id, title='상담', starts_at=datetime.now(timezone.utc)))
    revision = db.student_revision
    saved = repo.delete_enrollment(student.id, 2025)
    assert (saved.school_year, saved.grade, saved.classroom, saved.student_number) == (2026, 3, '3', '03')
    saved = repo.delete_enrollment(student.id, 2026)
    assert (saved.school_year, saved.grade, saved.classroom, saved.student_number) == (2024, 1, '1', '01')
    assert (saved.id, saved.name, saved.notes, saved.author, saved.created_at) == (
        latest.id, latest.name, latest.notes, latest.author, latest.created_at)
    assert [row.school_year for row in repo.enrollments(student.id)] == [2024]
    assert CounselingRepository(db).get(counseling.id) == counseling
    assert db.student_revision == revision + 2
    with pytest.raises(ConflictError):
        repo.delete_enrollment(student.id, 2024)
    with pytest.raises(NotFoundError):
        repo.delete_enrollment(student.id, 2023)
    with pytest.raises(NotFoundError):
        repo.delete_enrollment(999, 2024)
    assert repo.get(student.id) == saved
    assert len(repo.enrollments(student.id)) == 1
    assert db.student_revision == revision + 2


def test_v28_migration_preserves_counseling_and_student_author(db):
    repo = StudentRepository(db)
    student = repo.create(StudentInput(name='학생', **enrollment(2026).model_dump()))
    counseling = CounselingRepository(db).create(CounselingInput(
        student_id=student.id, title='기존 상담', starts_at=datetime.now(timezone.utc)))
    # Recreate the real v28 layout, including the old globally unique number.
    with db._session_lock, db._transaction(write=True, migration=True) as connection:
        connection.execute('DROP TABLE student_enrollments')
        connection.execute('ALTER TABLE students DROP COLUMN school_year')
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='students'").fetchone()[0]
        objects = [row[0] for row in connection.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='students' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        schema = schema.replace('"students"', 'old_students', 1).replace('student_number TEXT', 'student_number TEXT UNIQUE', 1)
        connection.execute(schema)
        connection.execute('INSERT INTO old_students SELECT * FROM students')
        connection.execute('DROP TABLE students')
        connection.execute('ALTER TABLE old_students RENAME TO students')
        for statement in objects:
            connection.execute(statement)
        connection.execute('PRAGMA user_version=28')
    SchoolSettingsRepository(db).save(SchoolSettings(counselor_name='새 교사'))
    db.initialize()
    migrated = repo.get(student.id)
    assert migrated.author == student.author
    assert migrated.school_year == current_school_year()
    assert repo.enrollments(student.id)[0].author == student.author
    assert CounselingRepository(db).get(counseling.id) == counseling
    repo.create(StudentInput(name='다른 반', **enrollment(current_school_year(), classroom='2').model_dump()))
    with db.session() as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    db.initialize()
    assert len(repo.enrollments(student.id)) == 1
