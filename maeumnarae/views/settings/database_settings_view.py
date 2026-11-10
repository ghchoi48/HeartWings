"""DB 폴더 열기, 암호화 백업 다운로드, 파일 업로드 복원 컨트롤."""

from datetime import datetime
from subprocess import SubprocessError

from maeumnarae.core.desktop import open_folder

from maeumnarae.core.secure_upload import SecureUpload, MAX_BACKUP_BYTES

from nicegui import events, run, ui

from maeumnarae.core.database import Database, DatabaseError
from maeumnarae.services.data_management.database_maintenance import (create_backup, reset_database, restore_backup,
                                                     soft_reset_database, reset_counseling_data)
from maeumnarae.views.students.roster_import_view import RosterImportView
from maeumnarae.views.students.year_preparation_view import YearPreparationView
from maeumnarae.views.data_management.legacy_import_view import LegacyImportView
from maeumnarae.views.shared.settings_card import settings_card
from maeumnarae.views.reports.journal_export_view import JournalExportView
from maeumnarae.views.reports.journal_print_view import build_all_print, invalidate_prints
from maeumnarae.views.data_management.partial_backup_view import PartialBackupView


def build_database_settings(database: Database, on_roster_import=None) -> None:
    busy = False
    uploaded: bytes | None = None
    import_views = []
    partial_views = []

    def set_busy(value: bool):
        nonlocal busy
        busy = value
        for control in (folder_button, backup, open_restore, upload, password, confirm, restore, cancel,
                        open_reset, reset_confirm, reset, reset_cancel,
                        open_counseling_reset, counseling_confirm, counseling_reset, counseling_cancel,
                        open_soft_reset, new_counselor, soft_confirm, soft_reset, soft_cancel):
            control.set_enabled(not value)
        for view in import_views:
            view.apply_busy(value)
        for view in partial_views:
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
            ui.download.content(content, f'마음나래-전체DB-{datetime.now():%Y%m%d-%H%M%S}.db',
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
            if event.file.size() > MAX_BACKUP_BYTES:
                raise ValueError('복원 파일은 256MB까지 지원합니다.')
            uploaded = await event.file.read()
        except (OSError, ValueError):
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

    def close_reset():
        if not busy:
            reset_dialog.close()

    async def initialize_database():
        if busy:
            return
        if not reset_confirm.value:
            ui.notify('DB 파일 삭제 확인에 체크해 주세요.', type='warning')
            return
        set_busy(True)
        reset.props('loading')
        try:
            await run.io_bound(reset_database, database)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            set_busy(False)
        else:
            invalidate_prints()
            reset_dialog.close()
            ui.navigate.to('/')
        finally:
            reset.props(remove='loading')

    async def handover_reset():
        if busy:
            return
        if not soft_confirm.value or not (new_counselor.value or '').strip():
            ui.notify('새 상담교사 이름을 입력하고 초기화 확인에 체크해 주세요.', type='warning')
            return
        set_busy(True)
        soft_reset.props('loading')
        try:
            await run.io_bound(soft_reset_database, database, new_counselor.value)
        except (DatabaseError, ValueError, OSError) as error:
            ui.notify(str(error), type='negative')
            set_busy(False)
        else:
            invalidate_prints()
            soft_dialog.close()
            ui.navigate.to('/')
        finally:
            soft_reset.props(remove='loading')

    def clear_soft_reset():
        new_counselor.set_value('')
        soft_confirm.set_value(False)

    async def initialize_counseling_data():
        if busy:
            return
        if not counseling_confirm.value:
            ui.notify('상담데이터 삭제 확인에 체크해 주세요.', type='warning')
            return
        set_busy(True)
        counseling_reset.props('loading')
        try:
            await run.io_bound(reset_counseling_data, database)
        except DatabaseError as error:
            ui.notify(str(error), type='negative')
            set_busy(False)
        else:
            invalidate_prints()
            counseling_dialog.close()
            ui.navigate.to('/')
        finally:
            counseling_reset.props(remove='loading')

    with settings_card('DB 관리', 'storage', '상담 데이터의 보관 상태와 백업을 관리하세요.', collapsible=True):
        folder_button = ui.button('DB 폴더 열기', icon='folder_open', on_click=open_database_folder).props('outline')
        ui.separator()
        with ui.element('div').classes('grid grid-cols-1 md:grid-cols-3 gap-6 w-full'):
            for kind in ('personal', 'counseling_school'):
                with ui.column().classes('w-full min-w-0 gap-3 rounded-xl border border-slate-200 p-5'):
                    partial_view = PartialBackupView(database, kind, lambda: busy, set_busy)
                    partial_view.build()
                    partial_views.append(partial_view)
            with ui.column().classes('w-full min-w-0 gap-3 rounded-xl border border-slate-200 p-5'):
                full_description = ('사용자 개인 데이터, 명부·상담 기록·첨부파일·학교 정보 등 DB에 저장된 모든 데이터를 '
                                    '백업 파일의 내용으로 교체합니다. DB 비밀번호도 백업 당시 비밀번호로 변경됩니다. '
                                    '테마·글꼴은 포함하지 않습니다.')
                ui.label('전체 DB 백업·복원').classes('font-semibold text-slate-700')
                ui.label(full_description).classes('text-sm text-slate-500')
                ui.label('현재 DB 비밀번호로 암호화하여 백업합니다. 복원에는 백업 당시 비밀번호가 필요합니다.').classes('text-sm text-slate-500')
                backup = ui.button('전체 DB 백업', icon='download', on_click=download_backup)
                with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                    ui.label('전체 DB 복원').classes('text-xl font-bold')
                    ui.label(full_description).classes('text-sm text-slate-600')
                    ui.label('256MB 이하의 전체 DB 백업 파일을 선택하세요. 복원 전 전체 DB를 자동 백업하며, 복원 후 백업 당시 비밀번호로 DB를 다시 열어야 합니다.').classes('text-sm text-slate-500')
                    upload = SecureUpload(label='복원할 DB 파일', auto_upload=True, max_files=1, max_file_size=MAX_BACKUP_BYTES,
                                       on_upload=receive_file).props('accept=.db,.sqlite,.sqlite3').classes('w-full')
                    upload.on('removed', remove_file)
                    password = ui.input('백업 파일 비밀번호', password=True, password_toggle_button=True).props(
                        'outlined autocomplete=current-password').classes('w-full')
                    confirm = ui.checkbox('현재 데이터를 백업 파일의 데이터로 교체합니다.')
                    with ui.row().classes('w-full justify-end gap-2'):
                        cancel = ui.button('취소', on_click=close_restore).props('flat')
                        restore = ui.button('복원', icon='restore', on_click=restore_database)
                dialog.on('hide', clear_restore)
                open_restore = ui.button('전체 DB 복원', icon='restore', on_click=dialog.open).props('outline')
        ui.separator()
        with ui.column().classes('w-full gap-4 rounded-xl border border-red-200 bg-red-50/50 p-5'):
            with ui.row().classes('items-center gap-2 text-red-700'):
                ui.icon('warning_amber', size='22px')
                ui.label('위험 구역').classes('text-lg font-bold')
            with ui.element('div').classes('grid grid-cols-1 md:grid-cols-3 gap-6 w-full'):
                with ui.column().classes('w-full min-w-0 gap-3'):
                    ui.label('인수인계 초기화').classes('font-semibold text-slate-700')
                    ui.label('위젯 배치·데이터, NEIS 인증키, Google 캘린더 연결과 사용자 캘린더를 삭제하고 상담교사 이름을 변경합니다.').classes('text-sm text-slate-500')
                    with ui.dialog().props('persistent') as soft_dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                        ui.label('인수인계 초기화를 진행할까요?').classes('text-xl font-bold text-slate-800')
                        ui.label('위젯 메모·할 일·배치 등 위젯 데이터, NEIS 인증키, Google 캘린더 연결 및 저장된 일정, 사용자 캘린더와 그 일정이 삭제됩니다.').classes('text-sm text-red-700')
                        ui.label('학생·교사 명부와 상담 기록, 기존 일지의 작성자 이름은 유지됩니다. Google 원본 캘린더는 삭제하지 않습니다.').classes('text-sm text-slate-600')
                        ui.label('초기화 전에 사용자 개인 데이터 백업을 내려받으면 해당 항목과 기존 상담교사 이름을 나중에 함께 복원할 수 있습니다. 초기화 후 현재 DB 비밀번호로 다시 열어 주세요.').classes('text-sm text-slate-600')
                        new_counselor = ui.input('새 상담교사 이름').props('outlined maxlength=100 required').classes('w-full')
                        soft_confirm = ui.checkbox('위 항목을 삭제하고 새 상담교사 이름으로 변경하겠습니다.')
                        with ui.row().classes('w-full justify-end gap-2'):
                            soft_cancel = ui.button('취소', on_click=lambda: soft_dialog.close() if not busy else None).props('flat')
                            soft_reset = ui.button('인수인계 초기화', icon='restart_alt', color='negative', on_click=handover_reset)
                    soft_dialog.on('hide', clear_soft_reset)
                    open_soft_reset = ui.button('인수인계 초기화 (Soft Reset)', icon='restart_alt',
                                                on_click=soft_dialog.open).props('outline')
                with ui.column().classes('w-full min-w-0 gap-3 border-t border-red-200 pt-6 md:border-t-0 md:border-l md:pt-0 md:pl-6'):
                    ui.label('상담데이터 초기화').classes('font-semibold text-slate-700')
                    ui.label('학교 설정과 개인 데이터를 유지하고 학생·교사 명부와 상담 관련 데이터를 삭제합니다.').classes('text-sm text-slate-500')
                    with ui.dialog().props('persistent') as counseling_dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                        ui.label('상담데이터를 초기화할까요?').classes('text-xl font-bold text-slate-800')
                        ui.label('학생·교사 명부, 개인·집단 상담 및 자문, 특별교육, 심리검사, 교육·행사 기록, 첨부파일, 상담 일정과 기존 자료 이관 이력·설정이 삭제됩니다.').classes('text-sm text-red-700')
                        ui.label('학교 정보, 상담교사 이름, NEIS 인증키, 위젯 메모·할 일·배치, Google 캘린더 연결과 사용자 캘린더·일정은 유지됩니다.').classes('text-sm text-slate-600')
                        ui.label('필요한 상담 데이터는 먼저 백업해 주세요. 백업 파일이 없으면 복구할 수 없습니다. 초기화 후 현재 DB 비밀번호로 다시 열어 주세요.').classes('text-sm text-slate-600')
                        counseling_confirm = ui.checkbox('위 상담데이터를 삭제하겠습니다.')
                        with ui.row().classes('w-full justify-end gap-2'):
                            counseling_cancel = ui.button('취소', on_click=lambda: counseling_dialog.close() if not busy else None).props('flat')
                            counseling_reset = ui.button('상담데이터 초기화', icon='delete_sweep', color='negative', on_click=initialize_counseling_data)
                    counseling_dialog.on('hide', lambda: counseling_confirm.set_value(False))
                    open_counseling_reset = ui.button('상담데이터 초기화', icon='delete_sweep', color='negative', on_click=counseling_dialog.open).props('outline')
                with ui.column().classes('w-full min-w-0 gap-3 border-t border-red-200 pt-6 md:border-t-0 md:border-l md:pt-0 md:pl-6'):
                    ui.label('DB 전체 초기화').classes('font-semibold text-slate-700')
                    ui.label('현재 DB 파일을 삭제하고 첫 실행 화면으로 돌아갑니다. 필요한 데이터는 먼저 백업해 주세요.').classes('text-sm text-slate-500')
                    with ui.dialog().props('persistent') as reset_dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                        ui.label('DB 전체를 초기화할까요?').classes('text-xl font-bold text-slate-800')
                        ui.label('학생, 상담 기록, 첨부파일 등 현재 DB에 저장된 모든 데이터가 삭제됩니다. 백업 파일이 없으면 복구할 수 없습니다.').classes('text-sm text-red-700')
                        ui.label(str(database.path.resolve())).classes('w-full break-all text-sm text-slate-500')
                        reset_confirm = ui.checkbox('현재 DB 파일을 삭제하고 처음부터 시작하겠습니다.')
                        with ui.row().classes('w-full justify-end gap-2'):
                            reset_cancel = ui.button('취소', on_click=close_reset).props('flat')
                            reset = ui.button('DB 전체 초기화', icon='delete_forever', color='negative', on_click=initialize_database)
                    reset_dialog.on('hide', lambda: reset_confirm.set_value(False))
                    open_reset = ui.button('DB 전체 초기화 (Hard Reset)', icon='delete_forever', color='negative', on_click=reset_dialog.open).props('outline')
    JournalExportView(database).build(collapsible=True)
    JournalExportView(database, ledger=True).build(collapsible=True)
    build_all_print(database)

    async def imported(kind):
        if on_roster_import is not None:
            await on_roster_import(kind)

    with settings_card('학생·교사 일괄 등록', 'group_add',
                       'XLSX 파일로 새 명부를 추가합니다. 기존 정보는 변경하지 않으며 오류가 있으면 전체 등록을 중단합니다.', collapsible=True):
        for kind in ('students', 'teachers'):
            view = RosterImportView(database, kind, lambda: busy, set_busy, imported)
            view.build()
            import_views.append(view)
    with settings_card('새 학년도 준비', 'school',
                       '전체 명단으로 학생 진급과 교사 갱신을 검토하고 확정합니다.', collapsible=True):
        for kind in ('students', 'teachers'):
            view = YearPreparationView(database, kind, lambda: busy, set_busy, imported)
            view.build()
            import_views.append(view)
    legacy = LegacyImportView(database, lambda: busy, set_busy, imported)
    legacy.build(collapsible=True)
    import_views.append(legacy)
