"""학교 정보 설정과 온보딩에서 함께 사용하는 학교 선택 UI."""

from collections.abc import Callable

from nicegui import run, ui

from maeumnarae.services.school.neis import OFFICES, NeisError, find_schools


async def _pick_school(office_code: str, school_level: str, school_name: str, api_key: str) -> dict | None:
    async def search():
        if not search_button.enabled:
            return
        results.clear()
        search_button.disable()
        query.disable()
        try:
            message.set_text('학교를 검색하고 있습니다…')
            rows = await run.io_bound(find_schools, office_code, query.value or '', api_key, school_level)
            if dialog.is_deleted:
                return
            message.set_text('학교명과 주소를 확인한 뒤 선택해 주세요.' if rows else
                             '선택한 시도교육청과 학교급에 일치하는 학교가 없습니다.')
            with results:
                for row in rows:
                    with ui.button(on_click=lambda row=row: dialog.submit(row), color=None).props(
                            'flat align=left no-caps').classes('w-full'):
                        with ui.row().classes('items-center gap-2 text-left'):
                            ui.label(row['SCHUL_NM']).classes('neis-school-name font-bold')
                            if row.get('ORG_RDNMA'):
                                ui.label(row['ORG_RDNMA']).classes('text-sm text-slate-500')
        except NeisError as error:
            if not dialog.is_deleted:
                message.set_text(str(error))
        finally:
            if not dialog.is_deleted:
                query.enable()
                search_button.enable()

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl max-h-[85vh] flex-nowrap'):
        ui.label('학교 찾기').classes('text-xl font-bold')
        with ui.row().classes('w-full flex-nowrap items-center'):
            query = ui.input('학교명', value=school_name).props('outlined autofocus maxlength=100').classes('flex-1')
            query.on('keydown.enter', search)
            search_button = ui.button('검색', icon='search', on_click=search)
        message = ui.label().props('role=status').classes('text-sm text-slate-500')
        results = ui.column().classes('w-full min-h-0 flex-nowrap overflow-auto gap-1')
        ui.button('닫기', on_click=dialog.close).props('flat').classes('self-end')
    try:
        return await dialog
    finally:
        if not dialog.is_deleted:
            dialog.delete()


def build_school_picker(fields: dict, api_key: Callable[[], str]) -> ui.button:
    async def open_search():
        office_code = fields['neis_office_code'].value
        school_level = fields['school_level'].value
        if office_code not in OFFICES or not school_level:
            ui.notify('시도교육청과 학교급을 먼저 선택해 주세요.', type='warning')
            return
        row = await _pick_school(office_code, school_level, fields['school_name'].value, api_key())
        if row:
            fields['school_name'].value = row['SCHUL_NM']
            fields['neis_school_code'].value = row['SD_SCHUL_CODE']

    with ui.row().classes('w-full flex-nowrap items-center gap-2'):
        level = fields['school_level']
        search_button = ui.button('학교 찾기', icon='search', on_click=open_search).props('outline').classes('shrink-0')
        fields['school_name'] = name = ui.input('학교명').props('outlined maxlength=100').classes('flex-1 min-w-0')
        name.bind_label_from(level, 'value', backward=lambda value: '센터명' if value == 'Wee센터' else '학교명')
        name.bind_enabled_from(level, 'enabled', backward=lambda enabled: enabled and level.value == 'Wee센터')
        level.on_value_change(lambda e: name.set_enabled(level.enabled and e.value == 'Wee센터'))
        fields['neis_school_code'] = ui.input('나이스 학교 코드').props('outlined').classes('flex-1 min-w-0').disable()
        for control in (search_button, fields['neis_school_code']):
            control.bind_visibility_from(level, 'value', backward=lambda value: value != 'Wee센터')
    return search_button
