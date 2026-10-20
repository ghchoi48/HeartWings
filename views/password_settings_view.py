"""현재 DB의 비밀번호 변경 폼. 비밀번호는 별도 설정 파일에 저장하지 않는다."""

from nicegui import run, ui

from database import Database, DatabaseError


def build_password_settings(database: Database) -> None:
    current = ui.input('현재 비밀번호', password=True, password_toggle_button=True).props(
        'outlined autocomplete=current-password').classes('w-full')
    new = ui.input('새 비밀번호', password=True, password_toggle_button=True).props(
        'outlined autocomplete=new-password').classes('w-full')
    confirmation = ui.input('새 비밀번호 확인', password=True, password_toggle_button=True).props(
        'outlined autocomplete=new-password').classes('w-full')
    ui.label('변경 후에는 새 비밀번호로 DB를 열 수 있습니다.').classes('text-sm text-slate-500')
    busy = False

    async def change():
        nonlocal busy
        if busy:
            return
        old_secret, new_secret = current.value or '', new.value or ''
        if not old_secret or not new_secret or not confirmation.value:
            ui.notify('현재 비밀번호와 새 비밀번호, 확인란을 모두 입력해 주세요.', type='negative')
            return
        if new_secret != confirmation.value:
            ui.notify('새 비밀번호와 확인 값이 일치하지 않습니다.', type='negative')
            return
        if old_secret == new_secret:
            ui.notify('새 비밀번호는 현재 비밀번호와 다르게 입력해 주세요.', type='negative')
            return
        busy = True
        for element in (current, new, confirmation, button):
            element.disable()
        button.props('loading')
        try:
            await run.io_bound(database.change_password, old_secret, new_secret)
            ui.notify('비밀번호를 변경했습니다. 다음 DB 열기부터 새 비밀번호를 사용하세요.', type='positive')
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
        finally:
            current.value = new.value = confirmation.value = ''
            old_secret = new_secret = ''
            for element in (current, new, confirmation, button):
                element.enable()
            button.props(remove='loading')
            busy = False

    button = ui.button('비밀번호 변경', icon='lock_reset', on_click=change)
