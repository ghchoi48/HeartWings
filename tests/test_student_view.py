"""실제 NiceGUI 요소와 가짜 저장소로 화면 상태 및 비동기 경쟁을 검사한다.

SQLCipher 암호화/CRUD 검증은 test_repositories.py의 별도 통합 테스트 책임이다.
"""

import asyncio
import inspect
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from nicegui import Client, ui
from nicegui.page import page
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.models import SchoolSettings, StudentTimelineEntry, Student, StudentEnrollment
from maeumnarae.views.student_view import PAGE_SIZE, StudentView, student_form_input


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
        self.client = Client(page('/test_student_view'))
        self.client.__enter__()
        self.students = Mock()
        self.students.list.return_value = []
        self.students.enrollments.return_value = []
        self.counseling = Mock()
        self.counseling.list_timeline.return_value = []
        self.host = ui.column()
        self.view = StudentView(self.students, self.counseling)
        with self.host, patch('maeumnarae.views.student_view.ui.timer'):
            self.view.build()
        self.io_patch = patch('maeumnarae.views.student_view.run.io_bound', side_effect=inline_io)
        self.io_patch.start()

    def tearDown(self):
        self.io_patch.stop()
        self.host.delete()
        self.client.__exit__(None, None, None)

    async def test_editor_reads_current_school_level_each_time(self):
        self.view.school = Mock()
        for level, count, existing_grade in [('초등학교', 6, 6), ('중학교', 3, 6), ('고등학교', 3, 2)]:
            self.view.school.get.return_value = SchoolSettings(school_level=level)

            async def interact(dialog):
                select = next(e for e in dialog.descendants()
                              if isinstance(e, ui.select) and e.props.get('label') == '*학년')
                self.assertEqual(list(select.options), list(range(1, count + 1)))
                self.assertEqual(select.value, existing_grade if existing_grade <= count else None)
                return None

            student = make_student().model_copy(update={'grade': existing_grade})
            with self.host, patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
                await self.view.open_editor(student)
            self.assertFalse(self.view.editor_open)

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

    async def test_editor_loads_year_and_saves_new_history(self):
        student = make_student().model_copy(update={'school_year': 2026, 'guardian_contact': '02-123-4567', 'gender': '여'})
        self.students.enrollments.return_value = [StudentEnrollment(
            student_id=student.id, school_year=2025, grade=1, classroom='4', student_number='08',
            created_at=student.created_at, updated_at=student.updated_at)]
        self.students.update.return_value = student

        async def interact(dialog):
            fields = {element.props.get('label'): element for element in dialog.descendants()
                      if isinstance(element, (ui.input, ui.number, ui.select))}
            self.assertEqual(fields['성별'].options, ['남', '여', '기타'])
            self.assertEqual(fields['성별'].value, '여')
            self.assertIs(fields['성별'].parent_slot, fields['*이름'].parent_slot)
            self.assertIs(fields['성별'].parent_slot, fields['별명'].parent_slot)
            fields['성별'].value = '기타'
            fields['*학년도'].value = 2025
            self.assertEqual(fields['*반'].value, '4')
            self.assertEqual(fields['번호'].value, '08')
            fields['*학년도'].value = 2027
            fields['*학년'].value = 3
            button = next(element for element in dialog.descendants()
                          if isinstance(element, ui.button) and element.text == '저장')
            handler = next(listener.handler for listener in button._event_listeners.values()
                           if listener.type == 'click')
            await inspect.getclosurevars(handler).nonlocals['callback']()
            self.assertTrue(dialog.submitted.is_set())
            return None

        with self.host, patch.object(ui.dialog, '__await__', lambda dialog: interact(dialog).__await__()):
            await self.view.open_editor(student)
        value = self.students.update.call_args.args[1]
        self.assertEqual((value.school_year, value.grade, value.classroom), (2027, 3, '4'))
        self.assertEqual(value.guardian_contact, student.guardian_contact)
        self.assertEqual(value.gender, '기타')

    async def test_enrollment_delete_buttons_and_latest_profile_refresh(self):
        student = make_student().model_copy(update={'school_year': 2026})
        history = [StudentEnrollment(
            student_id=student.id, school_year=year, grade=1, classroom='2',
            created_at=student.created_at, updated_at=student.updated_at) for year in (2026, 2025)]
        self.students.get.return_value = student
        self.students.enrollments.return_value = history
        with self.host:
            await self.view.load_profile(student.id)
            buttons = [element for element in self.view.detail.descendants()
                       if isinstance(element, ui.button) and '학적 이력 삭제' in element.props.get('aria-label', '')]
            self.assertEqual(len(buttons), 2)
            self.assertTrue(all(button.enabled for button in buttons))
            self.students.enrollments.return_value = history[1:]
            self.students.get.return_value = student.model_copy(update={'school_year': 2025})
            handler = next(listener.handler for listener in buttons[0]._event_listeners.values()
                           if listener.type == 'click')
            await inspect.getclosurevars(handler).nonlocals['callback']()
        self.students.delete_enrollment.assert_called_once_with(student.id, 2026)
        self.assertEqual(self.view.selected.school_year, 2025)
        remaining = [element for element in self.view.detail.descendants()
                     if isinstance(element, ui.button) and '학적 이력 삭제' in element.props.get('aria-label', '')]
        self.assertEqual(len(remaining), 1)
        self.assertFalse(remaining[0].enabled)
        self.assertFalse(self.view.editor_open)

    async def test_enrollment_delete_failure_keeps_profile_and_allows_retry(self):
        student = make_student()
        self.students.get.return_value = student
        self.students.delete_enrollment.side_effect = DatabaseError('삭제 실패')
        with self.host, patch('maeumnarae.views.student_view.ui.notify') as notify:
            await self.view.load_profile(student.id)
            await self.view.delete_enrollment(student.id, 2025)
        self.assertEqual(self.view.selected, student)
        self.assertFalse(self.view.editor_open)
        notify.assert_called_with('삭제 실패', type='negative')

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
                patch('maeumnarae.views.student_view.ui.notify'):
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
        with patch('maeumnarae.views.student_list.ui.notify') as notify:
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

        with patch('maeumnarae.views.student_view.run.io_bound', side_effect=delayed):
            old = asyncio.create_task(self.view.load_students())
            await started.wait()
            await self.view.load_students()
            release.set()
            await old
        self.assertEqual(self.view.student_list.table.rows[0]['name'], '현재 결과')


if __name__ == '__main__':
    unittest.main()
