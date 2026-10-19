"""독립 목록 인스턴스와 동기/비동기 선택 콜백을 검사한다."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui

from tests.test_student_view import inline_io, make_student
from views.student_list import StudentList


class StudentListTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.host = ui.column()

    async def test_independent_lists_and_callbacks(self):
        host = self.host
        first_repo, second_repo = Mock(), Mock()
        first_repo.list.return_value = [make_student(1, '첫 학생')]
        second_repo.list.return_value = [make_student(2, '다른 학생')]
        first_callback, second_callback = Mock(return_value=None), AsyncMock()
        first = StudentList(first_repo, first_callback)
        second = StudentList(second_repo, second_callback, page_size=20)
        try:
            with host:
                first.build(autoload=False)
                second.build(autoload=False)
            with patch('views.student_list.run.io_bound', side_effect=inline_io):
                await first.reload()
                await second.reload()
            first.table.filter = '첫 학생'
            self.assertNotEqual(first.table.filter, second.table.filter)
            self.assertEqual(first.table.rows[0]['id'], 1)
            self.assertEqual(second.table.rows[0]['id'], 2)
            self.assertEqual(second.table.pagination['rowsPerPage'], 20)
            await first._select_student(SimpleNamespace(args=1))
            await second._select_student(SimpleNamespace(args=2))
            first_callback.assert_called_once_with(1)
            second_callback.assert_awaited_once_with(2)
        finally:
            host.delete()
