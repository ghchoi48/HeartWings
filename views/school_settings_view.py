"""학교 정보 입력 및 저장 카드의 본문."""

from collections.abc import Callable

from nicegui import run, ui
from pydantic import ValidationError

from database import DatabaseError
from services.neis import OFFICES, NeisError, find_schools
from models import SchoolSettings
from repositories.school_settings_repo import SchoolSettingsRepository


def build_school_settings(repository: SchoolSettingsRepository,
                          on_change: Callable[[SchoolSettings], None] | None = None) -> None:
    fields = {}
    fields['school_name'] = ui.input('학교명').props('outlined maxlength=100').classes('w-full')
    fields['school_level'] = ui.select(
        ['초등학교', '중학교', '고등학교'], value='중학교', label='학교급',
    ).props('outlined').classes('w-full')
    ui.label('초등학교는 1~6학년, 중학교·고등학교는 1~3학년을 선택할 수 있습니다.').classes('text-sm text-slate-500')
    ui.label('상담실 정보').classes('font-semibold text-slate-700')
    fields['counselor_name'] = ui.input('상담교사 이름').props('outlined maxlength=100').classes('w-full')
    fields['office_number'] = ui.input('사무실 번호').props('outlined maxlength=50').classes('w-full')
    ui.separator()
    ui.label('나이스 급식 정보 연동').classes('font-semibold text-slate-700')
    fields['neis_office_code'] = ui.select({'': '선택 안 함', **OFFICES}, value='',
                                          label='시도교육청').props('outlined').classes('w-full')
    fields['neis_school_code'] = ui.input('나이스 학교 코드').props('outlined maxlength=7').classes('w-full')
    fields['neis_api_key'] = ui.input('나이스 인증키 (선택)', password=True,
                                     password_toggle_button=True).props('outlined maxlength=200').classes('w-full')
    ui.label('인증키 없이도 샘플 조회가 가능합니다. 정식 이용은 포털에서 발급받은 인증키를 입력하세요.').classes('text-sm text-slate-500')
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
                ui.label('급식을 조회할 학교 선택').classes('text-xl font-bold')
                ui.label('학교명과 주소를 확인하세요. 선택 후 학교 정보 저장을 눌러 주세요.').classes('text-sm text-slate-500')
                for row in rows:
                    def choose(row=row):
                        fields['school_name'].value = row['SCHUL_NM']
                        fields['neis_office_code'].value = row['ATPT_OFCDC_SC_CODE']
                        fields['neis_school_code'].value = row['SD_SCHUL_CODE']
                        if row.get('SCHUL_KND_SC_NM') in ('초등학교', '중학교', '고등학교'):
                            fields['school_level'].value = row['SCHUL_KND_SC_NM']
                        dialog.close()
                    ui.button(f"{row['SCHUL_NM']} · {row.get('ORG_RDNMA', '')}", on_click=choose).props('flat align=left').classes('w-full')
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
