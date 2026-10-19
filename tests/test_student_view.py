"""실제 NiceGUI 요소와 가짜 저장소로 화면 상태 및 비동기 경쟁을 검사한다.

SQLCipher 암호화/CRUD 검증은 test_repositories.py의 별도 통합 테스트 책임이다.
"""

import asyncio
import inspect
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nicegui import ui
from pydantic import ValidationError

from database import DatabaseError
from models import StudentTimelineEntry, Student
from views.student_view import PAGE_SIZE, StudentView, student_form_input


def make_student(student_id=1, name='가상 학생'):
    now = datetime.now(timezone.utc)
    return Student(id=student_id, name=name, grade=1, classroom='2', created_at=now, updated_at=now)


async def inline_io(function, *args, **kwargs):
    """테스트에서만 I/O 디스패처를 치환한다. 제품 DB 연결은 변경하지 않는다."""
    return function(*args, **kwargs)


class StudentFormTests(unittest.TestCase):
    def test_optional_blank_fields(self):
        result = student_form_input(dict(name=' 학생 ', grade=1, classroom='2',
                                         birth_date='', student_number='  '))
        self.assertEqual(result.name, '학생')
        self.assertIsNone(result.student_number)
        self.assertIsNone(result.birth_date)

    def test_invalid_date_and_missing_required_name(self):
        for values in (dict(name='', birth_date=''), dict(name='학생', birth_date='2026-02-30')):
            with self.assertRaises(ValidationError):
                student_form_input(dict(grade=1, classroom='2', **values))


class StudentViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.students = Mock()
        self.students.list.return_value = []
        self.counseling = Mock()
        self.counseling.list_timeline.return_value = []
        self.host = ui.column()
        self.view = StudentView(self.students, self.counseling)
        with self.host, patch('views.student_view.ui.timer'):
            self.view.build()
        self.io_patch = patch('views.student_view.run.io_bound', side_effect=inline_io)
        self.io_patch.start()

    def tearDown(self):
        self.io_patch.stop()
        self.host.delete()

    async def test_native_pagination_uses_complete_list(self):
        self.students.list.side_effect = [
            [make_student(i) for i in range(1, 1001)],
            [make_student(1001)],
        ]
        await self.view.load_students()
        self.assertEqual(len(self.view.student_list.table.rows), 1001)
        self.assertEqual(self.view.student_list.table.pagination['rowsPerPage'], PAGE_SIZE)
        self.students.list.assert_called_with(limit=1000, offset=1000)
        self.assertFalse(self.view.student_list.table.props.get('hide-pagination'))
        self.assertNotIn('hide-bottom', self.view.student_list.table.props)

    async def test_family_editor_save_and_retry(self):
        student = make_student().model_copy(update={'guardian_contact': '02-123-4567'})
        self.students.update_family.side_effect = [DatabaseError('저장 실패'), student]

        async def interact(dialog):
            elements = list(dialog.descendants())
            selects = [element for element in elements if isinstance(element, ui.select)]
            selects[0].value = '한부모 가정'
            selects[1].value = '해당 없음'
            save_button = next(element for element in elements
                               if isinstance(element, ui.button) and element.text == '저장')
            save = next(listener.handler for listener in save_button._event_listeners.values()
                        if listener.type == 'click')
            save = inspect.getclosurevars(save).nonlocals['callback']
            await save()
            self.assertFalse(dialog.submitted.is_set())
            self.assertTrue(save_button.enabled)
            self.assertTrue(any(isinstance(element, ui.label) and element.text == '저장 실패'
                                for element in elements))
            await save()
            self.assertTrue(dialog.submitted.is_set())
            return dialog._result

        with self.host, patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()), \
                patch('views.student_view.ui.notify'):
            await self.view.open_family_editor(student)
        student_id, family = self.students.update_family.call_args.args
        self.assertEqual(student_id, student.id)
        self.assertEqual(family.guardian_contact, student.guardian_contact)
        self.assertEqual(family.family_type, '한부모 가정')
        self.assertEqual(family.family_welfare_type, '해당 없음')
        self.assertFalse(self.view.editor_open)

    async def test_profile_timeline(self):
        student = make_student()
        self.students.get.return_value = student
        now = datetime.now(timezone.utc)
        self.counseling.list_timeline.return_value = [StudentTimelineEntry(
            id=1, student_id=student.id, starts_at=now, title='가상 상담', duration_minutes=50, category='개인상담',
            content_markdown='<script>unsafe()</script>', created_at=now, updated_at=now,
        )]
        await self.view.load_profile(student.id)
        self.assertEqual(self.view.selected, student)
        self.assertEqual(self.view.timeline_offset, 1)
        # 타임라인은 상담 본문 없이 요약 항목만 표시한다.
        texts = [element.text for element in self.view.timeline.descendants() if isinstance(element, ui.label)]
        self.assertNotIn('<script>unsafe()</script>', texts)
        self.assertIn('미지정 · 개인상담 · 50분', texts)
        self.assertIn('미입력 · 미입력', texts)

    async def test_group_timeline_summary(self):
        self.students.get.return_value = make_student()
        self.counseling.list_timeline.return_value = [StudentTimelineEntry(
            id=1, kind='group', starts_at=datetime.now(timezone.utc), title='첫 회기',
            group_name='사회성 집단', duration_minutes=60)]
        await self.view.load_profile(1)
        texts = [element.text for element in self.view.timeline.descendants() if isinstance(element, ui.label)]
        self.assertIn('집단상담 · 사회성 집단 · 60분', texts)
        self.assertIn('첫 회기', texts)

    async def test_special_education_timeline_summary(self):
        self.students.get.return_value = make_student()
        self.counseling.list_timeline.return_value = [StudentTimelineEntry(
            id=1, kind='special_education', starts_at=datetime.now(timezone.utc), title='상담 분야 미지정',
            education_name='학교생활 특별교육', counseling_target='보호자(가족)', duration_minutes=50)]
        await self.view.load_profile(1)
        texts = [element.text for element in self.view.timeline.descendants() if isinstance(element, ui.label)]
        self.assertIn('특별교육 · 학교생활 특별교육 · 50분', texts)
        self.assertIn('교육 대상: 보호자(가족)', texts)
        self.assertNotIn('상담 분야 미지정', texts)

    async def test_database_failure_clears_previous_rows(self):
        self.students.list.return_value = [make_student()]
        await self.view.load_students()
        self.students.list.side_effect = DatabaseError('조회 실패')
        with patch('views.student_list.ui.notify') as notify:
            await self.view.load_students()
        self.assertEqual(self.view.student_list.table.rows, [])
        notify.assert_called_once_with('조회 실패', type='negative')

    async def test_old_search_response_cannot_replace_new_results(self):
        started, release = asyncio.Event(), asyncio.Event()

        calls = 0

        async def delayed(function, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return [make_student(1, '이전 결과')]
            return [make_student(2, '현재 결과')]

        with patch('views.student_view.run.io_bound', side_effect=delayed):
            old = asyncio.create_task(self.view.load_students())
            await started.wait()
            await self.view.load_students()
            release.set()
            await old
        self.assertEqual(self.view.student_list.table.rows[0]['name'], '현재 결과')


if __name__ == '__main__':
    unittest.main()
