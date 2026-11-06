"""개인 데이터와 상담 데이터의 부분 백업·복원 컨트롤."""

from nicegui import events, run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.core.secure_upload import SecureUpload, MAX_BACKUP_BYTES
from maeumnarae.services.partial_backup import (
    KINDS, create_partial_backup, restore_partial_backup, partial_backup_filename,
)
from maeumnarae.views.journal_print_view import invalidate_prints


class PartialBackupView:
    def __init__(self, database, kind, is_busy, set_busy):
        self.database, self.kind = database, kind
        self.is_busy, self.set_busy = is_busy, set_busy
        self.uploaded = None
        self.controls = []

    def apply_busy(self, busy):
        for control in self.controls:
            control.set_enabled(not busy)

    def clear(self):
        self.uploaded = None
        self.password.value = ''
        self.confirm.value = False
        self.upload.reset()

    def remove_file(self):
        self.uploaded = None

    def close(self):
        if not self.is_busy():
            self.dialog.close()

    async def receive(self, event: events.UploadEventArguments):
        if self.is_busy():
            return
        self.set_busy(True)
        self.uploaded = None
        try:
            if event.file.size() > MAX_BACKUP_BYTES:
                raise ValueError()
            content = await event.file.read()
            if not content or len(content) > MAX_BACKUP_BYTES:
                raise ValueError()
            self.uploaded = content
        except (OSError, ValueError):
            ui.notify('256MB 이하의 부분 백업 파일을 선택해 주세요.', type='negative')
        finally:
            self.set_busy(False)

    async def download(self):
        if self.is_busy():
            return
        self.set_busy(True)
        try:
            content = await run.io_bound(create_partial_backup, self.database, self.kind)
            ui.download.content(content, partial_backup_filename(self.kind), media_type='application/octet-stream')
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
        finally:
            self.set_busy(False)

    async def restore(self):
        if self.is_busy():
            return
        if not self.uploaded or not self.password.value or not self.confirm.value:
            ui.notify('파일과 백업 파일 비밀번호를 입력하고 교체 확인에 체크해 주세요.', type='warning')
            return
        self.set_busy(True)
        secret = self.password.value
        self.password.value = ''
        try:
            recovery = await run.io_bound(restore_partial_backup, self.database, self.uploaded, secret, self.kind)
        except (DatabaseError, ValueError) as error:
            ui.notify(str(error), type='negative')
            self.set_busy(False)
        else:
            self.clear()
            self.dialog.close()
            invalidate_prints()
            with ui.dialog().props('persistent') as completed, ui.card().classes('w-full max-w-xl p-6 gap-4'):
                ui.label(f'{KINDS[self.kind]} 복원이 완료되었습니다.').classes('text-xl font-bold')
                ui.label('현재 DB 비밀번호로 다시 열어 주세요. 현재 DB 비밀번호는 변경되지 않았습니다.')
                ui.label('복원 전 전체 DB 자동 백업')
                ui.label(str(recovery)).classes('w-full break-all text-sm text-slate-500')
                ui.button('DB 다시 열기', icon='lock_open', on_click=lambda: ui.navigate.to('/'))
            completed.open()
        finally:
            secret = ''

    def build(self):
        title = KINDS[self.kind]
        description = (
            '위젯 메모·할 일·배치, NEIS 인증키, Google 연결·저장 일정, 사용자 캘린더·일정과 상담교사 이름을 '
            '함께 교체합니다. 상담 데이터 및 학교 정보는 유지됩니다. 테마·글꼴은 포함하지 않습니다.'
            if self.kind == 'personal' else
            '명부·상담 기록·첨부파일·학교 정보·상담용 캘린더 등 사용자 개인 데이터를 제외한 DB 데이터를 '
            '교체합니다. 현재 상담교사 이름·NEIS 인증키·위젯·Google 연결·사용자 캘린더는 유지됩니다.'
        )
        ui.label(f'{title} 백업·복원').classes('font-semibold text-slate-700')
        ui.label(description).classes('text-sm text-slate-500')
        ui.label('현재 DB 비밀번호로 암호화하여 백업합니다. 복원에는 백업 당시 비밀번호가 필요합니다.').classes('text-sm text-slate-500')
        download = ui.button(f'{title} 백업', icon='download', on_click=self.download)
        with ui.dialog().props('persistent') as self.dialog, ui.card().classes('w-full max-w-xl p-6 gap-4'):
            ui.label(f'{title} 복원').classes('text-xl font-bold')
            ui.label(description).classes('text-sm text-slate-600')
            ui.label('전용 부분 백업 파일만 지원합니다. 복원 전 전체 DB를 자동 백업하며, 복원 후 DB를 다시 열어야 합니다.').classes('text-sm text-slate-500')
            self.upload = SecureUpload(label='복원할 부분 백업 파일', auto_upload=True, max_files=1,
                                       max_file_size=MAX_BACKUP_BYTES, on_upload=self.receive).props('accept=.db,.sqlite,.sqlite3').classes('w-full')
            self.upload.on('removed', self.remove_file)
            self.password = ui.input('백업 파일 비밀번호', password=True, password_toggle_button=True).props(
                'outlined autocomplete=current-password').classes('w-full')
            self.confirm = ui.checkbox(f'현재 {title}를 백업 내용으로 교체합니다. 빈 항목도 반영됩니다.')
            with ui.row().classes('w-full justify-end gap-2'):
                cancel = ui.button('취소', on_click=self.close).props('flat')
                restore = ui.button('복원', icon='restore', on_click=self.restore)
        self.dialog.on('hide', self.clear)
        open_restore = ui.button(f'{title} 복원', icon='restore', on_click=self.dialog.open).props('outline')
        self.controls = [download, open_restore, self.upload, self.password, self.confirm, cancel, restore]
