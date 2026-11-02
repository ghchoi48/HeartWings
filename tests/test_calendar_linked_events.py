"""Linked education records use the counseling calendar and Korean dates."""
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from maeumnarae.core.database import Database
from maeumnarae.core.models import EducationEventInput, StudentInput, SpecialEducationInput, CounselingInput
from maeumnarae.repositories.calendar_repo import CalendarRepository
from maeumnarae.repositories.education_event_repo import EducationEventRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.special_education_repo import SpecialEducationRepository, SpecialEducationLogRepository
from maeumnarae.services.reporting import KST


class LinkedCalendarTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Database('test-password', Path(temp.name) / 'calendar.db')
        self.db.initialize()
        self.calendar = CalendarRepository(self.db)
        self.calendar_id = next(c.id for c in self.calendar.list() if c.source == 'counseling')
        self.education = EducationEventRepository(self.db)
        self.day = date(2026, 11, 2)

    def test_education_categories_time_and_calendar_filter(self):
        for category, clock in [('교육', '09:30'), ('행사', ''), ('단체심리검사', '15:00')]:
            self.education.save(EducationEventInput(title=category, category=category,
                                                   event_date=self.day, event_time=clock))
        events = self.calendar.events(self.day, self.day, [self.calendar_id])
        self.assertEqual(len(events), 3)
        self.assertTrue(all(e.source == 'education_event' and e.calendar_id == self.calendar_id for e in events))
        by_title = {e.title: e for e in events}
        self.assertTrue(by_title['행사'].all_day)
        self.assertEqual(by_title['행사'].duration_minutes, 1440)
        self.assertEqual(by_title['교육'].starts_at, datetime(2026, 11, 2, 9, 30, tzinfo=KST))
        self.assertFalse(by_title['교육'].all_day)
        self.assertEqual(self.calendar.events(self.day, self.day, []), [])
        self.assertEqual(self.calendar.events(self.day, self.day, [self.calendar_id], 'scheduled'), [])

    def test_previous_day_overlap_and_exact_midnight_end(self):
        for title, duration in [('이월', 90), ('자정 종료', 30)]:
            self.education.save(EducationEventInput(title=title, event_date=date(2026, 11, 1),
                                                   event_time='23:30', duration_minutes=duration))
        events = self.calendar.events(self.day, self.day, [self.calendar_id])
        self.assertEqual([e.title for e in events], ['이월'])

    def test_special_education_display_name_is_student_name(self):
        student = StudentRepository(self.db).create(StudentInput(name='테스트학생', grade=1, classroom='1'))
        case = SpecialEducationRepository(self.db).save(SpecialEducationInput(
            student_id=student.id, title='특별교육', law='학교폭력예방법'))
        SpecialEducationLogRepository(self.db).create(CounselingInput(
            student_id=student.id, case_id=case.id, title='일지 제목',
            starts_at=datetime(2026, 11, 2, 9, tzinfo=KST)))
        event, = self.calendar.events(self.day, self.day, [self.calendar_id])
        self.assertEqual(event.source, 'special_education')
        self.assertEqual(event.display_name, '테스트학생')
