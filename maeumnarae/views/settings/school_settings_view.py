"""학교 정보 입력 및 저장 카드의 본문."""

from collections.abc import Callable

from nicegui import run, ui
from pydantic import ValidationError

from maeumnarae.core.database import DatabaseError
from maeumnarae.services.school.neis import OFFICES
from maeumnarae.core.models import SchoolSettings
from maeumnarae.repositories.settings.school_settings_repo import SchoolSettingsRepository
from maeumnarae.views.shared.school_picker import build_school_picker


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
        search_button = build_school_picker(fields, lambda: fields['neis_api_key'].value or '')
    ui.separator()
    ui.label('상담실 정보').classes('font-semibold text-slate-700')
    fields['office_number'] = ui.input('사무실 전화번호').props('outlined maxlength=50').classes('w-full')
    fields['counselor_name'] = ui.input('상담교사 이름').props(
        'outlined maxlength=100 hide-hint hint="실명으로 입력해주세요. 일지 인쇄시 작성자 이름으로 사용됩니다."'
    ).classes('w-full')
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
    busy = False

    def enabled(value: bool):
        for key, field in fields.items():
            if key not in ('school_name', 'neis_school_code'):
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
