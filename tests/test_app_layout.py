"""학생 변경을 이미 생성된 모든 화면에 반영한다."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.views.app_layout import AppLayout


class StudentRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.students = Mock(database=SimpleNamespace(student_revision=0))
        self.layout = AppLayout(self.students, Mock(), Mock())
        for name in ('student_view', 'counseling_view'):
            setattr(self.layout, name, SimpleNamespace(
                editor_open=False, selected=SimpleNamespace(id=1),
                student_list=SimpleNamespace(reload=AsyncMock()),
                load_profile=AsyncMock(), select_student=AsyncMock(),
                student_heading=SimpleNamespace(text='이전 이름'),
            ))
        self.layout.group_view = SimpleNamespace(
            editor_open=False, selected=SimpleNamespace(id=2), select_group=AsyncMock())
        self.layout.calendar_view = SimpleNamespace(reload=AsyncMock())
        self.layout.statistics_view = SimpleNamespace(load=AsyncMock())

    @patch('maeumnarae.views.auto_lock.ui.run_javascript')
    async def test_build_after_login_container_is_deleted(self, _javascript):
        client = Client(page('/layout-test'))
        client.__enter__()
        content = ui.column()
        drawer = ui.left_drawer(value=False)
        header = ui.header()
        try:
            with content:
                login = ui.card()
            with login:
                content.clear()
                self.layout.build(content, drawer, header)
                drawer.show()
            timers = [element for element in content if isinstance(element, ui.timer)]
            self.assertEqual(len(timers), 1)
            self.assertIs(timers[0].parent_slot.parent, content)
            self.assertTrue(drawer.value)
            self.assertIn('students', self.layout.buttons)
        finally:
            content.delete()
            drawer.delete()
            header.delete()
            client.__exit__(None, None, None)

    async def test_refreshes_hidden_lists_and_selected_student(self):
        student = SimpleNamespace(id=1, name='수정 이름', grade=2, classroom='3')
        self.students.database.student_revision += 1
        with patch('maeumnarae.views.app_layout.run.io_bound', new=AsyncMock(return_value=student)):
            await self.layout.refresh_students()
        for view in (self.layout.student_view, self.layout.counseling_view):
            view.student_list.reload.assert_awaited_once()
        self.assertIs(self.layout.counseling_view.selected, student)
        self.assertEqual(self.layout.counseling_view.student_heading.text, '수정 이름 · 2학년 3반')
        self.layout.student_view.load_profile.assert_awaited_once_with(1)
        self.layout.group_view.select_group.assert_awaited_once_with(2)
        self.layout.calendar_view.reload.assert_awaited_once()
        self.layout.statistics_view.load.assert_awaited_once()
        await self.layout.refresh_students()
        self.layout.student_view.student_list.reload.assert_awaited_once()

    async def test_deleted_student_clears_counseling_selection(self):
        self.students.database.student_revision += 1
        with patch('maeumnarae.views.app_layout.run.io_bound', new=AsyncMock(return_value=None)):
            await self.layout.refresh_students()
        self.layout.counseling_view.select_student.assert_awaited_once_with(None)

    async def test_defers_refresh_while_editing_and_supports_unopened_pages(self):
        self.students.database.student_revision += 1
        self.layout.student_view.editor_open = True
        await self.layout.refresh_students()
        self.layout.student_view.student_list.reload.assert_not_awaited()
        self.assertEqual(self.layout.student_revision, 0)
        for name in ('student_view', 'counseling_view', 'group_view', 'calendar_view', 'statistics_view'):
            setattr(self.layout, name, None)
        await self.layout.refresh_students()
        self.assertEqual(self.layout.student_revision, 1)


class IntegratedCounselingTests(unittest.IsolatedAsyncioTestCase):
    async def test_student_button_tabs_and_student_switch(self):
        from datetime import datetime, timezone
        from maeumnarae.core.models import Student
        now = datetime.now(timezone.utc)
        students = Mock(database=SimpleNamespace(student_revision=0))
        students.enrollments.return_value = []
        students.get.side_effect = lambda student_id: Student(
            id=student_id, name=f'학생 {student_id}', grade=1, classroom='1',
            created_at=now, updated_at=now)
        counseling = Mock()
        counseling.list_timeline.return_value = []

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with Client(page('/integrated-counseling-test')), patch('maeumnarae.views.app_layout.ui.timer'), \
                patch('maeumnarae.views.auto_lock.ui.run_javascript'), \
                patch('maeumnarae.views.app_layout.run.io_bound', side_effect=invoke):
            layout = AppLayout(students, counseling, Mock())
            layout.build(ui.column(), ui.left_drawer(), ui.header())
            layout.navigate('students')
            await layout.student_view.load_profile(1)
            self.assertTrue(any(isinstance(e, ui.button) and e.text == '상담 일지'
                                for e in layout.student_view.detail.descendants()))
            layout.navigate('counseling')
            layout.counseling_view.cases = Mock()
            layout.counseling_view.cases.list.return_value = []
            layout.psychological_test_view.repository = Mock()
            layout.psychological_test_view.repository.list.return_value = []
            for student_id in (1, 2):
                await layout.student_view.on_counseling(student_id)
                self.assertEqual(layout.active_page, 'counseling')
                self.assertEqual(layout.counseling_tabs.value, 'logs')
                self.assertEqual(layout.counseling_view.selected.id, student_id)
                self.assertEqual(layout.psychological_test_view.selected.id, student_id)
                layout.counseling_tabs.set_value('tests')
                self.assertTrue(layout.psychological_test_view.add.enabled)
            self.assertNotIn('psychological_tests', layout.buttons)
            self.assertFalse(hasattr(layout.counseling_view, 'student_list'))
            self.assertFalse(hasattr(layout.psychological_test_view, 'student_list'))
            await layout.counseling_view.select_student(None)
            self.assertIsNone(layout.psychological_test_view.selected)
            self.assertFalse(layout.psychological_test_view.add.enabled)
