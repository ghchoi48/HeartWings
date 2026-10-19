"""학생 변경을 이미 생성된 모든 화면에 반영한다."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui

from views.app_layout import AppLayout


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

    async def test_build_after_login_container_is_deleted(self):
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

    async def test_refreshes_hidden_lists_and_selected_student(self):
        student = SimpleNamespace(id=1, name='수정 이름', grade=2, classroom='3')
        self.students.database.student_revision += 1
        with patch('views.app_layout.run.io_bound', new=AsyncMock(return_value=student)):
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
        with patch('views.app_layout.run.io_bound', new=AsyncMock(return_value=None)):
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
