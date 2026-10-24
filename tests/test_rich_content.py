"""일반 텍스트 호환 및 내용 서식 보존."""
import pytest
from nicegui import Client, ui
from nicegui.page import page
from unittest.mock import Mock

from maeumnarae.core.database import Database
from maeumnarae.core.models import EducationEventInput, PsychologicalTestInput, StudentInput
from maeumnarae.repositories.education_event_repo import EducationEventRepository
from maeumnarae.repositories.psychological_test_repo import PsychologicalTestRepository
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.views.counseling_content import editor_html
from maeumnarae.views.education_event_view import EducationEventView


def test_plain_text_keeps_literal_markup_and_line_breaks():
    html = editor_html('<b>일반 텍스트</b>\n두 번째 줄 & 끝', 'text')
    assert '&lt;b&gt;' in html
    assert '<br>' in html
    assert '&amp;' in html
    assert '<b>' not in html
    assert '<strong>내용</strong>' in editor_html('<strong>내용</strong><script>alert(1)</script>', 'html')
    assert '<script>' not in editor_html('<script>alert(1)</script>', 'html')


@pytest.mark.parametrize('kind', ['education_events', 'psychological_tests'])
def test_migration_and_html_roundtrip(tmp_path, kind):
    db = Database('test-only', tmp_path / 'rich.db')
    db.initialize()
    student = StudentRepository(db).create(StudentInput(name='학생', grade=1, classroom='1'))
    repo = EducationEventRepository(db) if kind == 'education_events' else PsychologicalTestRepository(db)
    value = (EducationEventInput(title='교육', event_date='2026-10-20', content='<b>원문</b>\n둘째 줄')
             if kind == 'education_events' else
             PsychologicalTestInput(student_id=student.id, title='검사', test_date='2026-10-20', content='<b>원문</b>\n둘째 줄'))
    saved = repo.save(value)
    with db.session(write=True) as connection:
        for table in ('education_events', 'psychological_tests'):
            connection.execute(f'ALTER TABLE {table} DROP COLUMN content_format')
        connection.execute('PRAGMA user_version=20')
    db.initialize()
    restored = repo.list()[0] if kind == 'education_events' else repo.list(student.id)[0]
    assert restored.content_format == 'text'
    assert restored.content == value.content
    rich = value.model_copy(update={'content': '<p><b>굵게</b></p><ul><li>목록</li></ul>', 'content_format': 'html'})
    updated = repo.save(rich, saved.id)
    created = repo.save(rich)
    db.initialize()
    records = repo.list() if kind == 'education_events' else repo.list(student.id)
    assert records == [created, updated]
    assert all(record.content_format == 'html' and record.content == rich.content for record in records)
    if kind == 'education_events':
        with Client(page('/rich-event-editor')):
            view = EducationEventView(Mock())
            view.details = ui.column()
            view.build_editor(restored)
            editors = [element for element in ui.context.client.elements.values() if isinstance(element, ui.editor)]
            assert len(editors) == 1
            assert '&lt;b&gt;' in editors[0].value
            assert '<br>' in editors[0].value
