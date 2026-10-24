"""DB 폴더 열기, 암호화 백업 다운로드, 파일 업로드 복원 컨트롤."""

from datetime import datetime
from subprocess import SubprocessError

from maeumnarae.core.desktop import open_folder

from nicegui import events, run, ui

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.services.database_maintenance import create_backup, restore_backup
from maeumnarae.views.roster_import_view import RosterImportView
from maeumnarae.views.legacy_import_view import LegacyImportView
from maeumnarae.views.settings_card import settings_card
from maeumnarae.views.journal_export_view import JournalExportView


def build_database_settings(database: Database, on_roster_import=None) -> None:
    busy = False
    uploaded: bytes | None = None
    import_views = []

    def set_busy(value: bool):
        nonlocal busy
        busy = value
        for control in (folder_button, backup, open_restore, upload, password, confirm, restore, cancel):
            control.set_enabled(not value)
        for view in import_views:
            view.apply_busy(value)
        if value:
            restore.props('loading')
        else:
            restore.props(remove='loading')

    async def open_database_folder():
        if busy:
            return
        set_busy(True)
        try:
            await run.io_bound(open_folder, database.path.resolve().parent)
        except (OSError, SubprocessError):
            ui.notify('DB 폴더를 열지 못했습니다. 폴더 위치와 접근 권한을 확인해 주세요.', type='negative')
        finally:
            set_busy(False)

    async def download_backup():
        if busy:
            return
        set_busy(True)
        try:
            content = await run.io_bound(create_backup, database)
            ui.download.content(content, f'maeumnarae-backup-{datetime.now():%Y%m%d-%H%M%S}.db',
                                media_type='application/octet-stream')
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
        finally:
            set_busy(False)

    def clear_restore():
        nonlocal uploaded
        uploaded = None
        password.value = ''
        confirm.value = False
        upload.reset()

    def close_restore():
        if not busy:
            clear_restore()
            dialog.close()

    async def receive_file(event: events.UploadEventArguments):
        nonlocal uploaded
        if busy:
            return
        set_busy(True)
        uploaded = None
        try:
            uploaded = await event.file.read()
        except OSError:
            ui.notify('백업 파일을 읽지 못했습니다. 다시 선택해 주세요.', type='negative')
        finally:
            set_busy(False)

    def remove_file():
        nonlocal uploaded
        uploaded = None

    async def restore_database():
        if busy:
            return
        if not uploaded or not password.value or not confirm.value:
            ui.notify('백업 파일과 해당 파일의 비밀번호를 입력하고 복원 확인에 체크해 주세요.', type='warning')
            return
        set_busy(True)
        secret = password.value
        password.value = ''
        try:
            recovery = await run.io_bound(restore_backup, database, uploaded, secret)
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
            set_busy(False)
        else:
            clear_restore()
            dialog.close()
            with ui.dialog().props('persistent') as completed, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                ui.label('DB 복원이 완료되었습니다.').classes('text-xl font-bold text-slate-800')
                ui.label('복원한 파일의 비밀번호로 DB를 다시 열어 주세요.').classes('text-slate-600')
                ui.label('복원 전 DB 자동 백업').classes('font-semibold text-slate-700')
                ui.label(str(recovery)).classes('w-full break-all text-sm text-slate-500')
                ui.button('DB 다시 열기', icon='lock_open', on_click=lambda: ui.navigate.to('/'))
            completed.open()
        finally:
            secret = ''

    with settings_card('DB 관리', 'storage', '상담 데이터의 보관 상태와 백업을 관리하세요.'):
        folder_button = ui.button('DB 폴더 열기', icon='folder_open', on_click=open_database_folder).props('outline')
        ui.separator()
        ui.label('DB 백업').classes('font-semibold text-slate-700')
        ui.label('현재 DB 비밀번호로 암호화된 백업 파일을 내려받습니다. 복원할 때 이 비밀번호가 필요합니다.').classes('text-sm text-slate-500')
        backup = ui.button('DB 백업 다운로드', icon='download', on_click=download_backup)
        ui.separator()
        ui.label('DB 복원').classes('font-semibold text-slate-700')
        ui.label('백업 파일로 현재 데이터를 교체합니다. 복원 전 DB는 자동 백업되며, 복원 후에는 DB를 다시 열어야 합니다.').classes('text-sm text-slate-500')
        with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
            ui.label('DB 복원').classes('text-xl font-bold text-slate-800')
            ui.label('백업 파일을 선택하고, 백업 당시의 DB 비밀번호를 입력하세요.').classes('text-sm text-slate-500')
            upload = ui.upload(label='복원할 DB 파일', auto_upload=True, max_files=1,
                               on_upload=receive_file).props('accept=.db,.sqlite,.sqlite3').classes('w-full')
            upload.on('removed', remove_file)
            password = ui.input('백업 파일 비밀번호', password=True, password_toggle_button=True).props(
                'outlined autocomplete=current-password').classes('w-full')
            confirm = ui.checkbox('현재 데이터를 백업 파일의 데이터로 교체합니다.')
            with ui.row().classes('w-full justify-end gap-2'):
                cancel = ui.button('취소', on_click=close_restore).props('flat')
                restore = ui.button('복원', icon='restore', on_click=restore_database)
        dialog.on('hide', clear_restore)
        open_restore = ui.button('백업 파일에서 복원', icon='restore', on_click=dialog.open).props('outline')
    JournalExportView(database).build()

    async def imported(kind):
        if on_roster_import is not None:
            await on_roster_import(kind)

    with settings_card('학생·교사 일괄 등록', 'group_add',
                       'XLSX 파일로 새 명부를 추가합니다. 기존 정보는 변경하지 않으며 오류가 있으면 전체 등록을 중단합니다.'):
        for kind in ('students', 'teachers'):
            view = RosterImportView(database, kind, lambda: busy, set_busy, imported)
            view.build()
            import_views.append(view)
    legacy = LegacyImportView(database, lambda: busy, set_busy, imported)
    legacy.build()
    import_views.append(legacy)
