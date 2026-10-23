import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nicegui import Client, ui
from nicegui.page import page

from database import Database
from services.legacy_import import parse_rows, PERSON_HEADERS
from views.legacy_import_view import LegacyImportView


def test_preview_save_and_option_invalidation(tmp_path):
    async def check():
        async def inline(function, *args):
            return function(*args)

        with Client(page('/legacy-test')):
            db = Database('key', tmp_path / 'view.db')
            db.initialize()
            busy = False

            def set_busy(value):
                nonlocal busy
                busy = value
                view.apply_busy(value)

            imported = AsyncMock()
            view = LegacyImportView(db, lambda: busy, set_busy, imported)
            view.build()
            rows = {'인적사항등록': [(7, dict.fromkeys(PERSON_HEADERS, '') | {
                '사례번호': 'P1', '성명/집단명': '학생', '성별/인원': '남', '학년': 1, '반': '1'})], '상담대장': []}
            batch = parse_rows(rows, 2026)
            rows['상담대장'].append((5, {'교시': '8교시'}))
            event = SimpleNamespace(file=SimpleNamespace(name='source.xlsb', read=AsyncMock(return_value=b'file')))
            with patch('views.legacy_import_view.run.io_bound', side_effect=inline), \
                    patch('views.legacy_import_view.read_rows', return_value=rows), \
                    patch.object(view.repository, 'preview', return_value=batch) as preview, \
                    patch('views.legacy_import_view.ui.notify'):
                assert not view.save_button.enabled
                await view.receive(event)
                assert view.save_button.enabled
                assert '8' in view.period_inputs
                tables = [element for element in view.preview.descendants() if isinstance(element, ui.table)]
                assert len(tables) == 2
                assert tables[0].rows[0]['kind'] == '학생'
                with db.session() as c:
                    assert c.execute('SELECT count(*) FROM students').fetchone()[0] == 0
                view.year.set_value(2025)
                assert view.batch is None
                assert not view.save_button.enabled
                await view.check()
                view.period_inputs['1'].set_value('08:50')
                view.period_inputs['8'].set_value('16:20')
                assert view.batch is None
                assert not view.save_button.enabled
                assert view.recheck.enabled
                await view.check()
                assert preview.call_args.args[2]['1'] == '08:50'
                assert preview.call_args.args[2]['8'] == '16:20'
                await view.save()
                assert view.batch is None
                assert not view.save_button.enabled
                imported.assert_awaited_once_with('legacy')
                with db.session() as c:
                    assert c.execute('SELECT count(*) FROM students').fetchone()[0] == 1
    asyncio.run(check())


def test_result_tables_include_all_rows_errors_and_consultation_kind():
    from datetime import datetime, timezone
    from models import TeacherInput, ConsultationInput
    from services.legacy_import import LegacyBatch, LegacyPerson, LegacyLog
    with Client(page('/legacy-tables')):
        view = LegacyImportView(None, lambda: False, lambda _: None, AsyncMock())
        view.build()
        value = ConsultationInput(teacher_id=1, title='자문 제목', starts_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        view.batch = LegacyBatch(
            tuple(LegacyPerson(i, str(i), TeacherInput(name=f'교사{i}')) for i in range(1, 26)),
            tuple(LegacyLog(i, str(i), value, '작성자') for i in range(1, 26)),
            tuple(f'상담대장 {i}행: 오류 {i}' for i in range(1, 61)), 'hash')
        view.render_results()
        tables = [element for element in view.preview.descendants() if isinstance(element, ui.table)]
        assert [len(table.rows) for table in tables] == [60, 25, 25]
        assert tables[0].rows[0]['sheet'] == '상담대장'
        assert tables[0].rows[0]['row'] == 1
        assert tables[1].rows[0]['kind'] == '교사'
        assert tables[2].rows[0]['kind'] == '교사 자문'
        assert tables[2].rows[0]['duration'] == 30


def test_psychological_test_preview_uses_test_date_and_time():
    from datetime import date
    from models import StudentInput, PsychologicalTestInput
    from services.legacy_import import LegacyBatch, LegacyPerson, LegacyLog
    with Client(page('/legacy-test-preview')):
        view = LegacyImportView(None, lambda: False, lambda _: None, AsyncMock())
        view.build()
        view.batch = LegacyBatch((LegacyPerson(7, 'P', StudentInput(name='학생', grade=1, classroom='1')),),
            (LegacyLog(5, 'P', PsychologicalTestInput(student_id=1, title='검사', test_date=date(2025, 5, 1),
                test_time='10:30', duration_minutes=40), '교사'),), (), 'hash')
        view.render_results()
        tables = [element for element in view.preview.descendants() if isinstance(element, ui.table)]
        assert tables[1].rows[0]['kind'] == '심리검사'
        assert tables[1].rows[0]['starts'] == '2025-05-01 10:30'
        assert tables[1].rows[0]['target'] == '학생'
