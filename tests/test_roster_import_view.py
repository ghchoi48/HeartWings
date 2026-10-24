"""DB 탭에서 서식 다운로드, 오류 차단, 명부 등록 및 새로고침 흐름 검증."""

import asyncio
import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nicegui import Client, ui
from nicegui.page import page
from openpyxl import load_workbook

from maeumnarae.core.database import Database
from maeumnarae.core.models import SchoolSettings
from maeumnarae.repositories.student_repo import StudentRepository
from maeumnarae.repositories.teacher_repo import TeacherRepository
from maeumnarae.views.database_settings_view import build_database_settings


def callback(button):
    listener = next(event.handler for event in button._event_listeners.values() if event.type == 'click')
    return inspect.getclosurevars(listener).nonlocals['callback']


def fill_template(content, values):
    workbook = load_workbook(BytesIO(content))
    for column, value in enumerate(values, 1):
        workbook.active.cell(2, column, value)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_database_tab_template_preview_and_register(tmp_path):
    async def check():
        async def inline(function, *args):
            return function(*args)

        with Client(page('/roster-import-test')) as client:
            db = Database('import-key', tmp_path / 'view.db')
            db.initialize(SchoolSettings(counselor_name='작성교사'))
            imported = AsyncMock()
            with patch('maeumnarae.views.database_settings_view.ui.timer'):
                build_database_settings(db, imported)
            elements = list(client.elements.values())
            buttons = {element.text: element for element in elements if isinstance(element, ui.button)}
            uploads = {element.props['label']: element for element in elements if isinstance(element, ui.upload)}
            with patch('maeumnarae.views.roster_import_view.run.io_bound', side_effect=inline), \
                    patch('maeumnarae.views.roster_import_view.ui.download.content') as download, \
                    patch('maeumnarae.views.roster_import_view.ui.notify'):
                for title, kind, values in [
                    ('학생', 'students', ['학생', 1, '03', '0001', '별명', '2012-02-03', '010-1234-5678']),
                    ('교사', 'teachers', ['교사', '010-1234-5678', '0012', '담임']),
                ]:
                    register = buttons[f'{title} 등록']
                    dialog = next(element for element in elements if isinstance(element, ui.dialog)
                                  and register in list(element.descendants()))
                    cancel = next(element for element in dialog.descendants()
                                  if isinstance(element, ui.button) and element.text == '취소')
                    assert not dialog.value
                    assert not register.enabled
                    await callback(buttons[f'{title} 서식 다운로드'])()
                    template = download.call_args.args[0]
                    assert download.call_args.args[1] == f'{title}_일괄등록_서식.xlsx'
                    assert template[:2] == b'PK'
                    upload = uploads[f'{title} XLSX 파일']
                    event = SimpleNamespace(file=SimpleNamespace(
                        name='roster.xlsx', read=AsyncMock(return_value=fill_template(template, values))))
                    await upload._upload_handlers[0](event)
                    assert dialog.value
                    assert register.enabled
                    if kind == 'students':
                        assert StudentRepository(db).list() == []
                    else:
                        assert TeacherRepository(db).list() == []
                    # 취소하면 저장 없이 닫히고 같은 파일을 다시 검사할 수 있다.
                    callback(cancel)()
                    assert not dialog.value
                    assert not register.enabled
                    assert imported.await_count == (0 if kind == 'students' else 1)
                    await upload._upload_handlers[0](event)
                    assert dialog.value
                    await callback(register)()
                    assert not dialog.value
                    assert not register.enabled
                    imported.assert_awaited_with(kind)
                    await callback(register)()  # 반복 클릭으로 중복 등록되지 않는다.
                assert len(StudentRepository(db).list()) == 1
                assert len(TeacherRepository(db).list()) == 1
                assert StudentRepository(db).list()[0].nickname == '별명'
                assert TeacherRepository(db).list()[0].extension == '0012'
                # 잘못된 행과 이미 등록된 자료는 등록 버튼을 활성화하지 않는다.
                for values in (['오류', 0, 1], ['학생', 1, '03', '0001']):
                    await callback(buttons['학생 서식 다운로드'])()
                    content = fill_template(download.call_args.args[0], values)
                    await uploads['학생 XLSX 파일']._upload_handlers[0](SimpleNamespace(
                        file=SimpleNamespace(name='invalid.xlsx', read=AsyncMock(return_value=content))))
                    assert not buttons['학생 등록'].enabled
                    student_dialog = next(element for element in elements if isinstance(element, ui.dialog)
                                          and buttons['학생 등록'] in list(element.descendants()))
                    assert student_dialog.value
                    await callback(buttons['학생 등록'])()
                assert len(StudentRepository(db).list()) == 1
    asyncio.run(check())
