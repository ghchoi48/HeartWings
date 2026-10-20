"""교사 저장, 기존 DB 마이그레이션 및 자문 목록 검증."""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from database import Database, NotFoundError
from models import Teacher, TeacherInput
from repositories.teacher_repo import TeacherRepository
from views.consultation_view import ConsultationView


def test_teacher_storage_and_migration(tmp_path):
    db = Database('test-only-password', tmp_path / 'teachers.db')
    db.initialize()
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE special_education_logs')
        connection.execute('DROP TABLE special_educations')
        connection.execute('DROP TABLE consultations')
        connection.execute('DROP TABLE teachers')
        connection.execute('DROP TABLE IF EXISTS education_events')
        connection.execute('PRAGMA user_version=10')
        connection.execute("""INSERT INTO students
            (name, grade, classroom, guardian_contact, notes, created_at, updated_at)
            VALUES ('기존 학생', 1, '1', '', '', '2026-01-01', '2026-01-01')""")
    db.initialize()
    repo = TeacherRepository(db)
    saved = repo.save(TeacherInput(name=' 교사 ', contact='010-1234-5678',
                                   extension='0012', responsibilities='학생생활'))
    assert saved.name == '교사'
    assert repo.get(saved.id) == saved
    assert saved.extension == '0012'
    updated = repo.save(TeacherInput(name='수정 교사'), saved.id)
    assert updated.created_at == saved.created_at
    assert updated.contact == ''
    assert repo.list() == [updated]
    repo.save(TeacherInput(name='수정 교사'))  # 동명이인 허용
    assert len(repo.list()) == 2
    with pytest.raises(NotFoundError):
        repo.save(TeacherInput(name='없는 교사'), 999)
    with pytest.raises(ValidationError):
        TeacherInput(name=' ')
    db.initialize()
    assert len(repo.list()) == 2
    with db.session() as connection:
        assert connection.execute('SELECT name FROM students').fetchone()[0] == '기존 학생'
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 24


class ConsultationViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_selection_and_refresh_preserve_search(self):
        with Client(page('/teacher-list-test')):
            now = datetime.now(timezone.utc)
            teacher = Teacher(id=1, name='교사', responsibilities='상담', extension='0012',
                              created_at=now, updated_at=now)
            repo = Mock()
            repo.list.return_value = [teacher]
            repo.get.return_value = teacher
            host = ui.column()
            view = ConsultationView(repo)
            view.consultations = Mock()
            view.consultations.list.return_value = []

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            try:
                with host, patch('views.consultation_view.ui.timer'):
                    view.build()
                with patch('views.consultation_view.run.io_bound', side_effect=invoke):
                    await view.reload()
                    self.assertEqual(view.table.rows[0]['name'], '교사')
                    view.table.filter = '상담'
                    await view.select_teacher(1)
                    self.assertEqual(view.selected, teacher)
                    repo.list.return_value = [teacher.model_copy(update={'name': '변경 이름'})]
                    await view.reload()
                    self.assertEqual(view.table.rows[0]['name'], '변경 이름')
                    self.assertEqual(view.table.filter, '상담')
                    repo.get.return_value = None
                    await view.select_teacher(999)
                    self.assertIsNone(view.selected)
            finally:
                host.delete()
