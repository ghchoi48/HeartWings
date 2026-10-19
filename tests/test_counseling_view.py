"""상담 폼 변환, 목록 격리, 조회 실패를 검증한다."""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui

from database import DatabaseError
from models import Counseling, Student, CounselingCase
from views.counseling_view import CounselingView, counseling_form_input


def form(**changes):
    return dict(title='상담', starts_at='2026-10-15T13:30', duration_minutes=50,
                category='개인상담', status='completed', content_markdown='  ## 원문\n\n', follow_up='') | changes


class CounselingFormTests(unittest.TestCase):
    def test_native_date_time_fields(self):
        values = form()
        values.pop('starts_at')
        result = counseling_form_input(1, dict(values, starts_on='2026-10-19', starts_time='13:30:15'))
        self.assertEqual(result.starts_at.isoformat(), '2026-10-19T13:30:15+09:00')
        for day, clock in [('', '13:30'), ('2026-02-30', '13:30'),
                           ('2026-10-19', ''), ('2026-10-19', '25:00'),
                           ('2026-10-19', '13:30+00:00')]:
            with self.subTest(day=day, clock=clock), self.assertRaises(ValueError):
                counseling_form_input(1, dict(values, starts_on=day, starts_time=clock))

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
        self.case = CounselingCase(id=1, student_id=1, title='사례', created_at=now, updated_at=now)
        self.view.cases = Mock()
        self.view.cases.list.return_value = [self.case]
        self.view.selected_case = self.case

    def tearDown(self):
        self.host.delete()

    async def test_wysiwyg_editor_preserves_html(self):
        with self.host:
            dialog, fields, _, _, _ = self.view.build_editor(self.student, None)
        try:
            self.assertIsInstance(fields['starts_on'], ui.date_input)
            self.assertIsInstance(fields['starts_time'], ui.time_input)
            self.assertIsInstance(fields['content_markdown'], ui.editor)
            self.assertTrue(fields['content_markdown'].visible)
            raw = '<div><b>작성 중</b></div>'
            fields['content_markdown'].value = raw
            self.assertEqual(fields['content_markdown'].value, raw)
        finally:
            dialog.delete()

    async def test_editor_restores_method_and_target(self):
        now = datetime.now(timezone.utc)
        entry = Counseling(id=1, created_at=now, updated_at=now,
                           **counseling_form_input(1, form(
                               counseling_method='전화', counseling_target='보호자')).model_dump())
        with self.host:
            dialog, fields, _, _, _ = self.view.build_editor(self.student, entry)
        try:
            self.assertEqual(fields['counseling_method'].value, '전화')
            self.assertEqual(fields['counseling_target'].value, '보호자')
            self.assertNotIn('counseling_method_other', fields)
            fields['counseling_method'].value = '사이버상담'
            fields['counseling_area'].value = '진로'
            self.assertNotIn('title', fields)
            value = counseling_form_input(1, {key: field.value for key, field in fields.items()})
            self.assertEqual(value.counseling_method, '사이버상담')
            self.assertEqual(value.counseling_area, '진로')
            self.assertEqual(value.title, '진로')
            fields['counseling_method'].value = '면담'
            value = counseling_form_input(1, {key: field.value for key, field in fields.items()})
            self.assertEqual(value.counseling_method, '면담')
            self.assertEqual(value.counseling_target, '보호자')
        finally:
            dialog.delete()

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

    async def test_shared_list_selection_loads_student_logs(self):
        self.students.get.return_value = self.student

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke):
            await self.view.student_list.on_select(self.student.id)
        self.assertEqual(self.view.selected, self.student)
        self.assertTrue(self.view.add.enabled)
        self.repo.list.assert_called_once_with(student_id=1, case_id=1, limit=21, offset=0)

    async def test_calendar_open_keeps_shared_student_list(self):
        now = datetime.now(timezone.utc)
        entry = Counseling(id=1, student_id=1, created_at=now, updated_at=now,
                           **counseling_form_input(1, form()).model_dump(exclude={'student_id'}))
        self.repo.get.return_value = entry
        self.students.get.return_value = self.student
        rows = [dict(id=1, name='가상 학생'), dict(id=2, name='다른 학생')]
        self.view.student_list.table.rows = rows

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke), \
                patch.object(self.view, 'open_editor', new_callable=AsyncMock) as editor:
            await self.view.open_record(entry.id)
        editor.assert_awaited_once_with(entry.id)
        self.assertEqual(self.view.selected, self.student)
        self.assertEqual(self.view.student_list.table.rows, rows)

    async def test_no_case_disables_new_log(self):
        self.students.get.return_value = self.student
        self.view.cases.list.return_value = []

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke):
            await self.view.select_student(self.student.id)
        self.assertIsNone(self.view.selected_case)
        self.assertFalse(self.view.add.enabled)
        self.repo.list.assert_not_called()

    async def test_case_selection_filters_and_resets_page(self):
        self.view.selected = self.student
        self.view.log_offset = 20
        second = self.case.model_copy(update={'id': 2, 'title': '두 번째 사례'})

        async def invoke(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch('views.counseling_view.run.io_bound', side_effect=invoke):
            await self.view.select_case(second)
        self.assertEqual(self.view.selected_case, second)
        self.repo.list.assert_called_once_with(student_id=1, case_id=2, limit=21, offset=0)
        self.assertEqual('상담 일지 목록', self.view.log_heading.text)

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
            await self.view.select_student(None)
            release.set()
            await task
        self.assertIsNone(self.view.selected)
        self.assertEqual(list(self.view.logs), [])


if __name__ == '__main__':
    unittest.main()
