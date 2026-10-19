"""실제 SQLCipher로만 수행하는 통합 테스트. 가짜/평문 DB로 대체하지 않는다."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from database import ConflictError, Database, DatabaseOpenError, NotFoundError
from models import CounselingInput, FamilyInput, StudentInput
from repositories.counseling_repo import CounselingRepository
from repositories.student_repo import StudentRepository


@pytest.fixture
def db(tmp_path):
    database = Database("test-only-'비밀번호", tmp_path / '상담 자료' / 'test.db')
    database.initialize()
    return database


def student_input(**changes):
    return StudentInput(**(dict(name='테스트학생', grade=2, classroom='3', student_number='2026-001') | changes))


def counseling_input(student_id, **changes):
    return CounselingInput(**(dict(student_id=student_id, title='상담',
        starts_at=datetime(2026, 10, 15, 9, tzinfo=timezone(timedelta(hours=9))),
        content_markdown='  **상담 원문**\n') | changes))


def test_student_crud_and_duplicate(db):
    repo = StudentRepository(db)
    student = repo.create(student_input())
    assert repo.get(student.id) == student
    with pytest.raises(ConflictError):
        repo.create(student_input())
    assert len(repo.list()) == 1
    updated = repo.update(student.id, student_input(name='수정학생'))
    assert updated.created_at == student.created_at
    assert repo.list(search='수정')[0].name == '수정학생'
    assert repo.list(search="' OR 1=1 --") == []
    repo.delete(student.id)
    assert repo.get(student.id) is None
    with pytest.raises(NotFoundError):
        repo.update(student.id, student_input())
    with pytest.raises(NotFoundError):
        repo.delete(student.id)


def test_family_update_preserves_student_fields(db):
    repo = StudentRepository(db)
    student = repo.create(student_input(notes='기존 메모'))
    updated = repo.update_family(student.id, FamilyInput(guardian_contact=' 02-123-4567 '))
    assert updated.guardian_contact == '02-123-4567'
    assert updated.model_dump(exclude={'guardian_contact', 'updated_at'}) == student.model_dump(
        exclude={'guardian_contact', 'updated_at'})
    assert repo.get(student.id) == updated
    assert repo.update_family(student.id, FamilyInput()).guardian_contact == ''
    with pytest.raises(ValidationError):
        FamilyInput(guardian_contact='1' * 201)
    with pytest.raises(NotFoundError):
        repo.update_family(student.id + 1, FamilyInput())


def test_counseling_crud_fk_and_timeline(db):
    students, repo = StudentRepository(db), CounselingRepository(db)
    student = students.create(student_input())
    entry = repo.create(counseling_input(student.id))
    assert repo.get(entry.id) == entry
    assert entry.content_markdown == '  **상담 원문**\n'
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert repo.list(student_id=student.id, start=start, end=start + timedelta(days=1)) == [entry]
    assert repo.list(end=start) == []  # 종료 경계는 제외한다.
    with pytest.raises(ConflictError):
        students.delete(student.id)
    with pytest.raises(ConflictError):
        repo.create(counseling_input(student.id + 999))
    updated = repo.update(entry.id, counseling_input(student.id, status='completed', title='완료'))
    assert updated.created_at == entry.created_at
    assert updated.status == 'completed'
    repo.delete(entry.id)
    assert repo.get(entry.id) is None
    with pytest.raises(NotFoundError):
        repo.delete(entry.id)
    with pytest.raises(NotFoundError):
        repo.update(entry.id, counseling_input(student.id))
    students.delete(student.id)


def test_encryption_wrong_password_and_reopen(db):
    StudentRepository(db).create(student_input())
    contents = db.path.read_bytes()
    assert not contents.startswith(b'SQLite format 3')
    assert '테스트학생'.encode() not in contents
    with sqlite3.connect(str(db.path)) as plaintext:
        with pytest.raises(sqlite3.DatabaseError):
            plaintext.execute('SELECT * FROM sqlite_master').fetchall()
    with pytest.raises(DatabaseOpenError):
        Database('wrong-password', db.path).initialize()
    reopened = Database("test-only-'비밀번호", db.path)
    reopened.initialize()
    assert len(StudentRepository(reopened).list()) == 1


def test_transaction_rolls_back(db):
    student = StudentRepository(db).create(student_input())
    with pytest.raises(RuntimeError):
        with db.session(write=True) as connection:
            connection.execute('DELETE FROM students WHERE id=?', (student.id,))
            raise RuntimeError('simulated failure')
    assert StudentRepository(db).get(student.id) == student


def test_invalid_inputs_and_pagination(db):
    with pytest.raises(ValidationError):
        student_input(name=' ')
    with pytest.raises(ValidationError):
        counseling_input(1, starts_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        StudentRepository(db).list(limit=0)
    with pytest.raises(ValueError):
        CounselingRepository(db).list(start=datetime(2026, 1, 1))


def test_future_schema_rejected_without_changes(db):
    from database import DatabaseError
    with db.session(write=True) as connection:
        connection.execute('PRAGMA user_version=99')
    with pytest.raises(DatabaseError):
        db.initialize()
    with db.session() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 99


def test_lock_revokes_existing_repository_and_allows_fresh_unlock(db):
    repo = StudentRepository(db)
    student = repo.create(student_input())
    db.lock()
    db.lock()  # 중복 잠금도 안전하다.
    with pytest.raises(DatabaseOpenError):
        repo.get(student.id)
    with pytest.raises(DatabaseOpenError):
        repo.create(student_input(student_number='blocked'))
    reopened = Database("test-only-'비밀번호", db.path)
    reopened.initialize()
    assert StudentRepository(reopened).get(student.id) == student


def test_family_members_round_trip_and_student_edit(db):
    repo = StudentRepository(db)
    student = repo.create(student_input())
    family = FamilyInput(
        guardian_contact='02-123-4567', family_type='직접 입력한 유형',
        family_welfare_type='직접 입력한 복지 유형',
        family_members=[
            dict(lives_together=True, relationship='모', name='가족1', age=42,
                 occupation='교사', contact='010-1111-2222'),
            dict(lives_together=False, relationship='형제', name='가족2', age=None),
        ],
    )
    repo.update_family(student.id, family)
    loaded = repo.get(student.id)
    assert FamilyInput.model_validate(loaded.model_dump(include=set(FamilyInput.model_fields))) == family
    repo.update(student.id, student_input(name='학생 수정', guardian_contact=family.guardian_contact))
    assert repo.get(student.id).family_members == family.family_members
    assert repo.list()[0].family_type == family.family_type
    repo.update_family(student.id, FamilyInput())
    assert repo.get(student.id).family_members == []
    for age in (-1, 151, 2.5):
        with pytest.raises(ValidationError):
            FamilyInput(family_members=[dict(age=age)])


def test_version_one_family_migration(tmp_path):
    from database import SCHEMA

    database = Database('migration-test', tmp_path / 'old.db')
    with database.session(write=True) as connection:
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute('PRAGMA user_version=1')
    repo = StudentRepository(database)
    student = repo.create(student_input())
    database.initialize()
    database.initialize()
    restored = repo.get(student.id)
    assert restored.name == student.name
    assert restored.family_members == []
    assert restored.family_type == ''
    repo.update_family(student.id, FamilyInput(family_type='확인'))
    assert repo.get(student.id).family_type == '확인'
