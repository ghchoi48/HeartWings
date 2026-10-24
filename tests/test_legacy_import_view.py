import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nicegui import Client, ui
from nicegui.page import page

from maeumnarae.core.database import Database
from maeumnarae.services.legacy_import import parse_rows, PERSON_HEADERS
from maeumnarae.views.legacy_import_view import LegacyImportView


def test_preview_save_and_option_invalidation(tmp_path):
    async def check():
        async def inline(function, *args, **kwargs):
            return function(*args, **kwargs)

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
            with patch('maeumnarae.views.legacy_import_view.run.io_bound', side_effect=inline), \
                    patch('maeumnarae.views.legacy_import_view.read_rows', return_value=rows), \
                    patch.object(view.repository, 'preview', return_value=batch) as preview, \
                    patch('maeumnarae.views.legacy_import_view.ui.notify'):
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
    from maeumnarae.core.models import TeacherInput, ConsultationInput
    from maeumnarae.services.legacy_import import LegacyBatch, LegacyPerson, LegacyLog
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
    from maeumnarae.core.models import StudentInput, PsychologicalTestInput
    from maeumnarae.services.legacy_import import LegacyBatch, LegacyPerson, LegacyLog
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


def test_edit_dialog_applies_fields_route_exclusion_and_cancel(tmp_path):
    import inspect
    from maeumnarae.services.legacy_import import LOG_HEADERS

    async def check():
        with Client(page('/legacy-edit')) as client:
            database = Database('key', tmp_path / 'edit.db')
            database.initialize()
            view = LegacyImportView(database, lambda: False, lambda _: None, AsyncMock())
            view.build()
            view.period_inputs['1'].set_value('09:10')
            view.rows = {'상담대장': [(5, dict.fromkeys(LOG_HEADERS, '') | {
                '일자': 46000, '교시': 1, '대분류': '연구', '상담내용': '본문'})], '인적사항등록': []}
            view.content = b'file'
            view.batch = parse_rows(view.rows, 2026, {'1': '09:10'})
            view.open_corrections()
            elements = list(client.elements.values())
            route = next(e for e in elements if isinstance(e, ui.select) and e.label == '등록할 일지')
            route.set_value('교육/행사')
            title = next(e for e in elements if isinstance(e, ui.input) and e.label == '상담제목')
            title.set_value('수정 제목')
            excluded = next(e for e in elements if isinstance(e, ui.checkbox) and e.text == '이 행 제외')
            excluded.set_value(True)
            button = next(e for e in elements if isinstance(e, ui.button) and e.text == '수정사항 저장 후 다음 오류')
            handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            with patch.object(view, 'check', new_callable=AsyncMock) as recheck:
                await inspect.getclosurevars(handler).nonlocals['callback']()
                recheck.assert_awaited_once()
            assert view.corrections == {('상담대장', 5): {'상담제목': '수정 제목'}}
            assert view.destinations == {5: '교육/행사'}
            assert view.excluded == {('상담대장', 5)}
            view.cancel_file()
            assert view.content is None and view.batch is None
            assert not view.rows and not view.corrections and not view.destinations and not view.excluded
            assert not view.recheck.enabled and not view.save_button.enabled
            reopened = LegacyImportView(database, lambda: False, lambda _: None, AsyncMock())
            reopened.build()
            assert reopened.period_inputs['1'].value == '09:10'
    asyncio.run(check())


def test_corrections_only_errors_and_continuous_save():
    import inspect
    from maeumnarae.services.legacy_import import LOG_HEADERS

    async def check():
        with Client(page('/legacy-continuous')) as client:
            view = LegacyImportView(None, lambda: False, lambda _: None, AsyncMock())
            view.build()
            view.rows = {'인적사항등록': [], '상담대장': [
                (number, dict.fromkeys(LOG_HEADERS, '') | {'일자': '2026-10-23', '교시': 1,
                 '시간(분)': 30, '대분류': major, '중분류': '심리검사', '상담구분': '집단심리검사'})
                for number, major in [(5, '교육'), (6, '연구'), (7, '검사')]]}
            view.content = b'file'

            async def recheck():
                view.clear()
                view.batch = parse_rows(view.rows, 2026, {'1': '09:10'},
                    corrections=view.corrections, destinations=view.destinations, excluded=view.excluded)
                view.render_results()

            await recheck()
            view.open_corrections()
            selector = next(e for e in client.elements.values() if isinstance(e, ui.select) and e.label == '수정할 행')
            button = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text == '수정사항 저장 후 다음 오류')
            dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog) and e.value)
            handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
            apply = inspect.getclosurevars(handler).nonlocals['callback']
            assert set(selector.options) == {'상담대장:5', '상담대장:6'}
            with patch.object(view, 'check', side_effect=recheck):
                # 해결되지 않은 오류는 같은 행을 유지한다.
                await apply()
                assert selector.value == '상담대장:5'
                for number in (5, 6):
                    route = next(e for e in dialog.descendants() if isinstance(e, ui.select) and e.label == '등록할 일지')
                    route.set_value('교육/행사')
                    await apply()
                    assert dialog.value
                    assert f'상담대장:{number}' not in selector.options
                assert not view.batch.errors
                assert not selector.options and not button.enabled
                assert view.destinations == {5: '교육/행사', 6: '교육/행사'}
                assert any(isinstance(e, ui.label) and '모든 오류가 해결' in e.text for e in dialog.descendants())
    asyncio.run(check())


def test_special_education_option_law_and_preview():
    import inspect
    from maeumnarae.services.legacy_import import LOG_HEADERS

    async def check():
        with Client(page('/legacy-special')) as client:
            view = LegacyImportView(None, lambda: False, lambda _: None, AsyncMock())
            view.build()
            view.rows = {'인적사항등록': [(7, dict.fromkeys(PERSON_HEADERS, '') | {
                '사례번호': 'P1', '성명/집단명': '학생', '성별/인원': '남', '학년': 1, '반': '1'})],
                '상담대장': [(5, dict.fromkeys(LOG_HEADERS, '') | {'사례번호': 'P1',
                '일자': '2026-10-23', '교시': 1, '시간(분)': 40, '대분류': '교육'})]}
            view.batch = parse_rows(view.rows, 2026, {'1': '09:10'})
            view.open_corrections()
            route = next(e for e in client.elements.values() if isinstance(e, ui.select) and e.label == '등록할 일지')
            assert '특별교육' in route.options
            route.set_value('특별교육')
            law = next(e for e in client.elements.values() if isinstance(e, ui.select) and e.label == '특별교육 근거 법률')
            law.set_value('교원지위법')
            button = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text == '수정사항 저장 후 다음 오류')
            handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')

            async def recheck():
                view.clear()
                view.batch = parse_rows(view.rows, 2026, {'1': '09:10'}, destinations=view.destinations,
                                        special_laws=view.special_laws)
                view.render_results()

            with patch.object(view, 'check', side_effect=recheck):
                await inspect.getclosurevars(handler).nonlocals['callback']()
            assert view.special_laws == {5: '교원지위법'}
            assert not view.batch.errors
            tables = [e for e in view.preview.descendants() if isinstance(e, ui.table)]
            assert tables[-1].rows[0]['kind'] == '특별교육'
            view.cancel_file()
            assert not view.special_laws
    asyncio.run(check())
