"""상담 폼 변환, 목록 격리, 조회 실패를 검증한다."""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nicegui import ui

from database import DatabaseError
from models import Counseling, Student
from views.counseling_view import CounselingView, counseling_form_input


def form(**changes):
    return dict(title='상담', starts_at='2026-10-15T13:30', duration_minutes=50,
                category='개인상담', status='completed', content_markdown='  ## 원문\n\n', follow_up='') | changes


class CounselingFormTests(unittest.TestCase):
    def test_korean_time_and_verbatim_markdown(self):
        result = counseling_form_input(1, form())
        self.assertEqual(result.starts_at.astimezone(timezone.utc).hour, 4)
        self.assertEqual(result.content_markdown, '  ## 원문\n\n')

    def test_invalid_fields(self):
        for changes in [dict(title=' '), dict(starts_at=''), dict(starts_at='2026-02-30T12:00'),
                        dict(duration_minutes=0), dict(duration_minutes=1.5), dict(status='invalid'),
                        dict(starts_at='2026-10-15T13:30+00:00')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                counseling_form_input(1, form(**changes))


class CounselingViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.students, self.repo = Mock(), Mock()
        self.repo.list.return_value = []
        self.host = ui.column()
        self.view = CounselingView(self.students, self.repo)
        with self.host, patch('views.counseling_view.ui.timer'):
            self.view.build()
        now = datetime.now(timezone.utc)
        self.student = Student(id=1, name='가상 학생', grade=1, classroom='2', created_at=now, updated_at=now)

    def tearDown(self):
        self.host.delete()

    async def test_empty_and_failed_log_query(self):
        self.view.selected = self.student

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke):
            await self.view.load_logs()
            self.assertIn('등록된 상담 일지가 없습니다', self.view.log_message.text)
            self.repo.list.side_effect = DatabaseError('조회 실패')
            await self.view.load_logs()
        self.assertEqual(self.view.log_message.text, '조회 실패')

    async def test_previous_student_response_is_discarded(self):
        started, release = asyncio.Event(), asyncio.Event()
        now = datetime.now(timezone.utc)
        entry = Counseling(id=1, student_id=1, created_at=now, updated_at=now,
                           **(counseling_form_input(1, form()).model_dump(exclude={'student_id'})))

        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return [entry]

        self.view.selected = self.student
        with patch('views.counseling_view.run.io_bound', side_effect=delayed):
            task = asyncio.create_task(self.view.load_logs())
            await started.wait()
            self.view.table.selected = []
            await self.view.select_student()
            release.set()
            await task
        self.assertIsNone(self.view.selected)
        self.assertEqual(list(self.view.logs), [])


if __name__ == '__main__':
    unittest.main()
