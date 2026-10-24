"""교사 저장, 기존 DB 마이그레이션 및 자문 목록 검증."""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from maeumnarae.core.database import Database, NotFoundError
from maeumnarae.core.models import Teacher, TeacherInput
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.views.consultation_view import ConsultationView


def test_teacher_storage_and_migration(tmp_path):
    db = Database('test-only-password', tmp_path / 'teachers.db')
    db.initialize()
    with db.session(write=True) as connection:
        connection.execute('DROP TABLE student_enrollments')
        connection.execute('ALTER TABLE students DROP COLUMN school_year')
        # 이전 버전에는 첨부 테이블이 없으므로 부모 테이블보다 먼저 제거한다.
        connection.execute('DROP TABLE IF EXISTS journal_attachments')
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
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 29


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
                with host, patch('maeumnarae.views.consultation_view.ui.timer'):
                    view.build()
                with patch('maeumnarae.views.consultation_view.run.io_bound', side_effect=invoke):
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


def test_teacher_search_ranks_best_match_before_alphabetical_order(tmp_path):
    db = Database('test-only-password', tmp_path / 'ranked.db')
    db.initialize()
    repo = TeacherRepository(db)
    repo.save(TeacherInput(name='가나다', responsibilities='김민수'))
    repo.save(TeacherInput(name='김민수 선생님'))
    exact = repo.save(TeacherInput(name='김민수'))
    assert repo.search('김민수', limit=1) == [exact]
    assert repo.search('김민', limit=1) == [exact]
    assert repo.search('민수', limit=1) == [exact]
    assert repo.search('없는 검색어', limit=1) == []


def test_teacher_search_by_extension_preserves_zeros_and_ranks_exact_match(tmp_path):
    db = Database('test-only-password', tmp_path / 'extensions.db')
    db.initialize()
    repo = TeacherRepository(db)
    repo.save(TeacherInput(name='가', responsibilities='0012'))
    repo.save(TeacherInput(name='나', extension='00123'))
    exact = repo.save(TeacherInput(name='상담 교사', extension='0012'))
    assert repo.search(' 0012 ', limit=1) == [exact]
    assert exact in repo.search('001')
    assert exact in repo.search('012')
    assert repo.search('9999') == []
    literal = repo.save(TeacherInput(name='특수 내선', extension='10%_!'))
    for query in ('%', '_', '!'):
        assert repo.search(query) == [literal]


class TeacherSearchWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_empty_blank_and_single_search_result(self):
        from maeumnarae.widgets.teacher_search import TeacherSearch
        with Client(page('/teacher-widget-test')):
            repo = Mock()
            repo.search.return_value = []
            widget = TeacherSearch(None, repo)
            host = ui.column()
            with host:
                widget.build()
            repo.search.assert_not_called()

            async def invoke(function, *args, **kwargs):
                return function(*args, **kwargs)

            with patch('maeumnarae.widgets.teacher_search.run.io_bound', side_effect=invoke):
                widget.query.value = '   '
                await widget.search()
                repo.search.assert_not_called()
                widget.query.value = ' 김민수 '
                await widget.search()
                repo.search.assert_called_once_with('김민수', limit=1)
            host.delete()
