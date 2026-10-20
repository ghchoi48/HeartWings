"""학교 정보 입력 및 저장 카드의 본문."""

from collections.abc import Callable

from nicegui import run, ui
from pydantic import ValidationError

from database import DatabaseError
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
    busy = False

    def enabled(value: bool):
        for field in fields.values():
            field.set_enabled(value)
        save_button.set_enabled(value)

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
            ui.notify('입력 길이와 학교급을 확인해 주세요.', type='negative')
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
