"""실제 암호화 DB에서 삭제 범위와 트랜잭션의 원자성을 검증한다."""
from datetime import date, datetime, timezone

import pytest

from maeumnarae.core.database import ConflictError, Database, NotFoundError
from maeumnarae.core.models import (StudentInput, TeacherInput, CounselingCaseInput, CounselingInput,
                    SpecialEducationInput, GroupCounselingInput, GroupLogInput,
                    ConsultationInput, PsychologicalTestInput, EducationEventInput,
                    CalendarInput, CalendarEventInput)
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.repositories.case_repo import CaseRepository
from maeumnarae.repositories.counseling_repo import CounselingRepository
from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.repositories.group_counseling_repo import GroupCounselingRepository
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.repositories.education_event_repo import EducationEventRepository
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.deletion_repo import DeletionRepository, TARGETS


@pytest.fixture
def records(tmp_path):
    db = Database('test-only-password', tmp_path / 'deletion.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    teacher = TeacherRepository(db).save(TeacherInput(name='교사'))
    case = CaseRepository(db).save(CounselingCaseInput(student_id=student.id, title='사례'))
    start = datetime(2026, 10, 23, 9, tzinfo=timezone.utc)
    log = CounselingRepository(db).create(CounselingInput(student_id=student.id, case_id=case.id, title='상담', starts_at=start))
    special = SpecialEducationRepository(db).save(SpecialEducationInput(student_id=student.id, title='교육', law='교원지위법'))
    special_log = SpecialEducationLogRepository(db).create(CounselingInput(student_id=student.id, case_id=special.id, title='교육 일지', starts_at=start))
    groups = GroupCounselingRepository(db)
    group = groups.save(GroupCounselingInput(name='집단', student_ids=[student.id]))
    group_log = groups.save_log(GroupLogInput(group_id=group.id, title='집단 일지', starts_at=start))
    consultation = ConsultationRepository(db).save(ConsultationInput(teacher_id=teacher.id, title='자문', starts_at=start))
    test = PsychologicalTestRepository(db).save(PsychologicalTestInput(student_id=student.id, title='검사', test_date=date(2026, 10, 23)))
    education = EducationEventRepository(db).save(EducationEventInput(title='행사', event_date=date(2026, 10, 23)))
    calendars = CalendarRepository(db)
    calendar = calendars.create(CalendarInput(name='일정'))
    calendars.save_event(CalendarEventInput(calendar_id=calendar.id, title='회의', starts_at=start))
    with db.session() as connection:
        event_id = connection.execute('SELECT id FROM calendar_events').fetchone()[0]
    return db, dict(student=student.id, teacher=teacher.id, case=case.id, counseling=log.id,
                    special=special.id, special_log=special_log.id, group=group.id,
                    group_log=group_log.id, consultation=consultation.id, test=test.id,
                    education=education.id, event=event_id)


@pytest.mark.parametrize('kind', TARGETS)
def test_delete_removes_only_target_and_dependents(records, kind):
    db, ids = records
    dependents = {
        'student': {'case', 'counseling', 'special', 'special_log', 'test'},
        'teacher': {'consultation'}, 'case': {'counseling'},
        'special': {'special_log'}, 'group': {'group_log'},
    }
    revision = db.student_revision
    DeletionRepository(db).delete(kind, ids[kind])
    removed = {kind} | dependents.get(kind, set())
    with db.session() as connection:
        for key, (table, _, _) in TARGETS.items():
            exists = connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (ids[key],)).fetchone()
            assert bool(exists) == (key not in removed), key
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        if kind in ('student', 'group'):
            assert not connection.execute('SELECT * FROM group_counseling_members').fetchall()
        if kind == 'student':
            assert not connection.execute('SELECT * FROM student_enrollments').fetchall()
    assert db.student_revision == revision + (kind == 'student')
    with pytest.raises(NotFoundError):
        DeletionRepository(db).delete(kind, ids[kind])


def test_failed_parent_delete_rolls_back_children(records):
    db, ids = records
    with db.session(write=True) as connection:
        connection.execute("""CREATE TRIGGER prevent_student_delete BEFORE DELETE ON students
                            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    revision = db.student_revision
    with pytest.raises(ConflictError):
        DeletionRepository(db).delete('student', ids['student'])
    with db.session() as connection:
        for kind, (table, _, _) in TARGETS.items():
            assert connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (ids[kind],)).fetchone()
    assert db.student_revision == revision
