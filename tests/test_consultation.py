"""자문 일지 저장 격리와 에디터 저장/재시도 검증."""

import asyncio
import inspect
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database, DatabaseError, NotFoundError
from maeumnarae.core.models import Consultation, ConsultationInput, TeacherInput, Teacher
from maeumnarae.repositories.consultation_repo import ConsultationRepository
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.views.consultation_view import ConsultationView


def test_migration_and_teacher_isolation(tmp_path):
    db = Database('test-only', tmp_path / 'consultation.db')
    db.initialize()
    teachers = TeacherRepository(db)
    first = teachers.save(TeacherInput(name='첫 교사'))
    second = teachers.save(TeacherInput(name='다른 교사'))
    with db.session(write=True) as connection:
        # 이전 버전에는 첨부 테이블이 없으므로 부모 테이블보다 먼저 제거한다.
        connection.execute('DROP TABLE IF EXISTS journal_attachments')
        connection.execute('DROP TABLE special_education_logs')
        connection.execute('DROP TABLE special_educations')
        connection.execute('DROP TABLE consultations')
        connection.execute('DROP TABLE IF EXISTS education_events')
        connection.execute('PRAGMA user_version=11')
    db.initialize()
    db.initialize()
    assert teachers.get(first.id) == first
    repo = ConsultationRepository(db)
    value = ConsultationInput(teacher_id=first.id, title='자문', starts_at=datetime.now(timezone.utc),
                              content_html='<div><b>내용</b></div>', follow_up='후속 조치', consultation_area='학교학습')
    saved = repo.save(value)
    assert repo.get(saved.id, first.id) == saved
    assert saved.consultation_area == '학교학습'
    assert repo.get(saved.id, second.id) is None
    assert repo.list(second.id) == []
    with pytest.raises(NotFoundError):
        repo.save(value.model_copy(update={'teacher_id': second.id}), saved.id)
    updated = repo.save(value.model_copy(update={'title': '수정', 'consultation_area': '기타'}), saved.id)
    assert updated.created_at == saved.created_at
    assert updated.title == '수정'
    assert updated.consultation_area == '기타'
    later = repo.save(value)
    assert repo.list(first.id, limit=1) == [later]
    assert repo.list(first.id, limit=1, offset=1) == [updated]


class ConsultationEditorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = Client(page('/consultation-test'))
        with self.client:
            self.host = ui.column()
        self.view = ConsultationView(Mock())
        now = datetime.now(timezone.utc)
        self.teacher = Teacher(id=1, name='교사', created_at=now, updated_at=now)
        with self.host, patch('maeumnarae.views.consultation_view.ui.timer'):
            self.view.build()
        self.view.selected = self.teacher
        self.view.show_logs()
        self.view.consultations = Mock()

    def tearDown(self):
        self.host.delete()

    async def test_save_validation_failure_retry_and_html_cleaning(self):
        self.view.load_logs = AsyncMock()
        self.view.consultations.save.side_effect = [DatabaseError('저장 실패'), Mock()]
        build = self.view.build_log_editor
        captured = {}

        def capture(*args):
            result = build(*args)
            captured['parts'] = result
            return result

        async def interact(dialog):
            _, fields, message, save_button, _ = captured['parts']
            handler = next(item.handler for item in save_button._event_listeners.values() if item.type == 'click')
            save = inspect.getclosurevars(handler).nonlocals['callback']
            await save()
            self.view.consultations.save.assert_not_called()
            self.assertNotIn('title', fields)
            self.assertEqual(message.text, '자문 분야를 선택해 주세요.')
            self.assertIsInstance(fields['consultation_area'], ui.select)
            self.assertEqual(fields['consultation_area'].options,
                             ['학교학습', '사회성발달', '정서발달', '진로발달', '행동발달', '기타'])
            fields['consultation_area'].value = '정서발달'
            fields['content_html'].value = '<b>내용</b><script>alert(1)</script>'
            await save()
            self.assertEqual(message.text, '저장 실패')
            self.assertEqual(fields['consultation_area'].value, '정서발달')
            self.assertTrue(save_button.enabled)
            await save()
            value = self.view.consultations.save.call_args.args[0]
            self.assertEqual(value.teacher_id, 1)
            self.assertEqual(value.consultation_area, '정서발달')
            self.assertEqual(value.title, '정서발달')
            self.assertNotIn('<script', value.content_html)
            self.assertEqual(value.starts_at.utcoffset().total_seconds(), 9 * 3600)
            return True

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with self.host, patch.object(self.view, 'build_log_editor', side_effect=capture), \
                patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()), \
                patch('maeumnarae.views.consultation_view.run.io_bound', side_effect=invoke):
            await self.view.open_log_editor()
        self.assertFalse(self.view.editor_open)
        self.view.load_logs.assert_awaited_once()

    async def test_list_uses_area_instead_of_legacy_title(self):
        now = datetime.now(timezone.utc)
        entry = Consultation(id=1, teacher_id=1, title='이전 제목', starts_at=now,
                             consultation_area='학교학습', created_at=now, updated_at=now)
        self.view.consultations.list.return_value = [entry]
        self.view.consultations.count.return_value = 1

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('maeumnarae.views.consultation_view.run.io_bound', side_effect=invoke):
            await self.view.load_logs()
            labels = [e.text for e in self.view.logs.descendants() if isinstance(e, ui.label)]
            self.assertIn('학교학습', labels)
            self.assertNotIn('이전 제목', labels)
            self.view.consultations.list.return_value = [entry.model_copy(update={'consultation_area': ''})]
            await self.view.load_logs()
            labels = [e.text for e in self.view.logs.descendants() if isinstance(e, ui.label)]
            self.assertIn('자문 분야 미지정', labels)

    async def test_old_teacher_logs_cannot_replace_new_selection(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return [], 0, 1

        with patch('maeumnarae.views.consultation_view.run.io_bound', side_effect=delayed):
            task = asyncio.create_task(self.view.load_logs())
            await started.wait()
            self.view.log_request += 1
            self.view.selected = None
            self.view.show_logs()
            release.set()
            await task
        self.assertEqual(self.view.log_message.text, '')
        self.assertFalse(self.view.add_log.enabled)


def test_consultation_area_migration(tmp_path):
    db = Database('test-only', tmp_path / 'area.db')
    db.initialize()
    teacher = TeacherRepository(db).save(TeacherInput(name='교사'))
    repo = ConsultationRepository(db)
    saved = repo.save(ConsultationInput(teacher_id=teacher.id, title='기존 자문', starts_at=datetime.now(timezone.utc)))
    with db.session(write=True) as connection:
        connection.execute('ALTER TABLE consultations DROP COLUMN consultation_area')
        connection.execute('PRAGMA user_version=15')
    db.initialize()
    db.initialize()
    assert repo.get(saved.id, teacher.id) == saved
    updated = repo.save(ConsultationInput(teacher_id=teacher.id, title=saved.title,
                        starts_at=saved.starts_at, consultation_area='진로발달'), saved.id)
    with Client(page('/consultation-area-edit')):
        view = ConsultationView(Mock())
        dialog, fields, *_ = view.build_log_editor(teacher, updated)
        assert fields['consultation_area'].value == '진로발달'
        assert 'title' not in fields
        dialog.delete()
