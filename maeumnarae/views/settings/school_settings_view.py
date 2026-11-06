"""학교 정보 입력 및 저장 카드의 본문."""

from collections.abc import Callable

from nicegui import run, ui
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.school.neis import OFFICES, NeisError, find_schools
from maeumnarae.core.models import SchoolSettings
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository


def build_school_settings(repository: SchoolSettingsRepository,
                          on_change: Callable[[SchoolSettings], None] | None = None) -> None:
    fields = {}
    with ui.column().classes('w-full gap-5'):
        ui.label('학교 정보').classes('font-semibold text-slate-700')
        fields['neis_office_code'] = ui.select({'': '선택 안 함', **OFFICES}, value='',
                                              label='시도교육청').props('outlined').classes('w-full')
        fields['school_level'] = ui.select(
            ['초등학교', '중학교', '고등학교', 'Wee센터'], value='중학교', label='학교급',
        ).props('outlined').classes('w-full')
        fields['school_name'] = ui.input('학교명').props('outlined maxlength=100').classes('w-full')
        fields['school_name'].bind_label_from(
            fields['school_level'], 'value', backward=lambda level: '센터명' if level == 'Wee센터' else '학교명')
    ui.separator()
    ui.label('상담실 정보').classes('font-semibold text-slate-700')
    fields['counselor_name'] = ui.input('상담교사 이름').props('outlined maxlength=100').classes('w-full')
    fields['office_number'] = ui.input('사무실 번호').props('outlined maxlength=50').classes('w-full')
    ui.separator()
    ui.label('나이스 연동').classes('font-semibold text-slate-700')
    fields['neis_api_key'] = ui.input('NEIS API 인증키', password=True, password_toggle_button=True).props(
        'outlined maxlength=200 autocomplete=off').classes('w-full')
    with ui.expansion('인증키 용도 및 발급 방법', icon='help_outline').classes('w-full'):
        ui.label('학교 검색, 급식 식단과 학사일정 조회에 사용하는 나이스 교육정보 개방 포털의 인증키입니다. '
                 '학사일정 연동에는 인증키가 필요하며, 저장한 키는 다른 나이스 조회에도 함께 사용됩니다.')
        ui.label('1. 아래 나이스 교육정보 개방 포털에 접속하여 SNS 계정으로 로그인합니다.')
        ui.label('2. 활용가이드 → 인증키 신청에서 안내에 따라 신청하고 발급된 키를 복사합니다.')
        ui.label('3. 위 입력란에 붙여 넣고, 시도교육청과 학교 코드를 확인한 뒤 학교 정보 저장을 누릅니다.')
        ui.link('나이스 인증키 신청 열기', 'https://open.neis.go.kr/portal/guide/actKeyPage.do', new_tab=True)
    fields['neis_school_code'] = ui.input('나이스 학교 코드').props('outlined maxlength=7').classes('w-full')
    busy = False

    async def search_school():
        nonlocal busy
        if busy:
            return
        busy = True
        enabled(False)
        try:
            rows = await run.io_bound(find_schools, fields['neis_office_code'].value or '',
                                      fields['school_name'].value or '', fields['neis_api_key'].value or '')
            if not rows:
                ui.notify('일치하는 학교가 없습니다. 학교명과 교육청을 확인해 주세요.', type='warning')
                return
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl p-6'):
                ui.label('나이스 연동 학교 선택').classes('text-xl font-bold')
                ui.label('학교명과 주소를 확인하세요. 선택 후 학교 정보 저장을 눌러 주세요.').classes('text-sm text-slate-500')
                for row in rows:
                    def choose(row=row):
                        fields['school_name'].value = row['SCHUL_NM']
                        fields['neis_office_code'].value = row['ATPT_OFCDC_SC_CODE']
                        fields['neis_school_code'].value = row['SD_SCHUL_CODE']
                        if row.get('SCHUL_KND_SC_NM') in ('초등학교', '중학교', '고등학교'):
                            fields['school_level'].value = row['SCHUL_KND_SC_NM']
                        dialog.close()
                    with ui.button(on_click=choose, color=None).props('flat align=left no-caps').classes('w-full'):
                        with ui.row().classes('items-center gap-2 text-left'):
                            ui.label(row['SCHUL_NM']).classes('neis-school-name font-bold')
                            if row.get('ORG_RDNMA'):
                                ui.label(row['ORG_RDNMA']).classes('text-sm text-slate-500')
                ui.button('닫기', on_click=dialog.close).props('flat')
            dialog.open()
        except NeisError as error:
            ui.notify(str(error), type='negative')
        finally:
            busy = False
            enabled(True)

    search_button = ui.button('학교명으로 나이스 코드 찾기', icon='search', on_click=search_school).props('outline')

    def enabled(value: bool):
        for field in fields.values():
            field.set_enabled(value)
        save_button.set_enabled(value)
        search_button.set_enabled(value)

    async def load():
        nonlocal busy
        busy = True
        enabled(False)
        try:
            settings = await run.io_bound(repository.get)
            for key, field in fields.items():
                field.value = getattr(settings, key)
            if on_change is not None:
                on_change(settings)
            enabled(True)
            retry.set_visibility(False)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            retry.set_visibility(True)
        finally:
            busy = False

    async def save():
        nonlocal busy
        if busy:
            return
        busy = True
        enabled(False)
        try:
            settings = SchoolSettings(**{key: field.value or '' for key, field in fields.items()})
            settings = await run.io_bound(repository.save, settings)
            for key, field in fields.items():
                field.value = getattr(settings, key)
            if on_change is not None:
                on_change(settings)
            ui.notify('학교 정보를 저장했습니다.', type='positive')
        except ValidationError:
            ui.notify('입력 길이, 학교급과 나이스 학교 코드(숫자 7자리)를 확인해 주세요.', type='negative')
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            busy = False
            enabled(True)

    save_button = ui.button('학교 정보 저장', icon='save', on_click=save)
    retry = ui.button('학교 정보 다시 불러오기', on_click=load).props('flat')
    retry.set_visibility(False)
    enabled(False)
    ui.timer(0.01, load, once=True)
