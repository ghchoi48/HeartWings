"""DB 정보, 암호화 백업 다운로드, 파일 업로드 복원 컨트롤."""

from datetime import datetime

from nicegui import events, run, ui

from database import Database, DatabaseError
from services.database_maintenance import create_backup, database_info, restore_backup
from views.roster_import_view import RosterImportView


def build_database_settings(database: Database, on_roster_import=None) -> None:
    busy = False
    uploaded: bytes | None = None
    import_views = []

    def set_busy(value: bool):
        nonlocal busy
        busy = value
        for control in (refresh, backup, open_restore, upload, password, confirm, restore, cancel):
            control.set_enabled(not value)
        for view in import_views:
            view.apply_busy(value)
        if value:
            restore.props('loading')
        else:
            restore.props(remove='loading')

    async def refresh_info():
        if busy:
            return
        set_busy(True)
        try:
            info = await run.io_bound(database_info, database)
            path.set_text(info['path'])
            size.set_text(f"{info['size']:,} bytes ({info['size'] / 1024 / 1024:.2f} MB)")
            version.set_text(f"스키마 {info['schema_version']} · SQLCipher {info['cipher_version']}")
            counts.set_text(f"학생 {info['students']:,}명 · 개인 상담 일지 {info['counseling']:,}건")
        except (DatabaseError, OSError) as error:
            ui.notify(str(error) if isinstance(error, DatabaseError) else 'DB 정보를 불러오지 못했습니다.', type='negative')
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

    ui.label('DB 정보').classes('font-semibold text-slate-700')
    ui.label('파일 위치').classes('text-sm text-slate-500')
    path = ui.label('불러오는 중…').classes('w-full break-all text-slate-700')
    size = ui.label().classes('text-slate-700')
    version = ui.label().classes('text-sm text-slate-500')
    counts = ui.label().classes('text-sm text-slate-500')
    refresh = ui.button('DB 정보 새로고침', icon='refresh', on_click=refresh_info).props('flat')
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
    ui.separator()
    ui.label('학생·교사 일괄 등록').classes('font-semibold text-slate-700')
    ui.label('XLSX 파일로 새 명부를 추가합니다. 기존 정보는 변경하지 않으며 오류가 있으면 전체 등록을 중단합니다.').classes('text-sm text-slate-500')

    async def imported(kind):
        await refresh_info()
        if on_roster_import is not None:
            await on_roster_import(kind)

    for kind in ('students', 'teachers'):
        view = RosterImportView(database, kind, lambda: busy, set_busy, imported)
        view.build()
        import_views.append(view)
    ui.timer(0.01, refresh_info, once=True)
