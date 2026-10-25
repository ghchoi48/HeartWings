"""모든 일지가 공유하는 파일 첨부·다운로드·삭제 창."""
import asyncio
from contextlib import asynccontextmanager

from maeumnarae.core.secure_upload import SecureUpload

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.attachment_repo import AttachmentRepository, DraftAttachments, MAX_ATTACHMENT_BYTES


class AttachmentView:
    def __init__(self, repository: AttachmentRepository | DraftAttachments, lock=None):
        self.repository = repository
        self.lock = lock or asyncio.Lock()
        self.pending = 0

    def build(self):
        with ui.dialog().props('persistent') as self.dialog, ui.card().classes('w-full max-w-2xl p-6 gap-4'):
            ui.label('일지 첨부파일').classes('text-2xl font-bold')
            draft = isinstance(self.repository, DraftAttachments) and self.repository.record_id is None
            ui.label('파일당 최대 20MB · 한 번에 10개까지 · 일지 저장 시 첨부파일도 함께 저장됩니다. 작성을 취소하면 첨부파일도 폐기됩니다.' if draft else
                     '파일당 최대 20MB · 한 번에 10개까지 · 첨부와 삭제는 즉시 저장됩니다. 일지 삭제 시 첨부파일도 함께 삭제됩니다.').classes('text-sm text-slate-500')
            self.upload = SecureUpload(label='파일 선택 또는 끌어놓기', auto_upload=True, multiple=True,
                                    max_file_size=MAX_ATTACHMENT_BYTES, on_upload=self.receive,
                                    on_rejected=lambda: ui.notify('파일당 20MB 이하의 파일을 선택해 주세요.', type='warning')).classes('w-full')
            self.message = ui.label().classes('text-sm text-red-700')
            self.files = ui.column().classes('w-full gap-2')
            self.close = ui.button('닫기', on_click=lambda: self.dialog.submit(None)).props('flat')

    def set_busy(self, busy):
        self.upload.set_enabled(not busy)
        self.close.set_enabled(not busy)
        for element in self.files.descendants():
            if isinstance(element, ui.button):
                element.set_enabled(not busy)

    @asynccontextmanager
    async def operation(self):
        self.pending += 1
        self.set_busy(True)
        try:
            async with self.lock:
                self.message.text = ''
                yield
        except (DatabaseError, ValueError, OSError) as error:
            self.message.text = str(error)
        finally:
            self.pending -= 1
            if not self.dialog.is_deleted:
                self.set_busy(self.pending > 0)

    async def refresh(self):
        entries = await run.io_bound(self.repository.list)
        self.files.clear()
        with self.files:
            if not entries:
                ui.label('첨부파일이 없습니다.').classes('text-slate-500')
            for entry in entries:
                with ui.row().classes('w-full items-center flex-nowrap border rounded p-3'):
                    with ui.column().classes('grow min-w-0 gap-1'):
                        ui.label(entry.filename).classes('break-all')
                        ui.label(f'{entry.size:,}바이트').classes('text-xs text-slate-500')
                    ui.button(icon='download', on_click=lambda entry=entry: self.download(entry)).props('flat round aria-label="첨부파일 다운로드"').tooltip('다운로드')
                    ui.button(icon='delete_outline', on_click=lambda entry=entry: self.remove(entry)).props('flat round color=negative aria-label="첨부파일 삭제"').tooltip('삭제')
        self.set_busy(self.pending > 0)

    async def receive(self, event):
        if self.dialog.is_deleted:
            return
        async with self.operation():
            if event.file.size() > MAX_ATTACHMENT_BYTES:
                raise ValueError('첨부파일은 파일당 20MB까지 저장할 수 있습니다.')
            content = await event.file.read()
            await run.io_bound(self.repository.add, event.file.name, content)
            await self.refresh()
            draft = isinstance(self.repository, DraftAttachments) and self.repository.record_id is None
            ui.notify('첨부파일을 추가했습니다. 일지를 저장하면 함께 저장됩니다.' if draft else '첨부파일을 저장했습니다.', type='positive')

    async def download(self, entry):
        async with self.operation():
            filename, content = await run.io_bound(self.repository.download, entry.id)
            ui.download.content(content, filename, media_type='application/octet-stream')

    async def remove(self, entry):
        async with self.operation():
            with ui.dialog().props('persistent') as confirm, ui.card():
                ui.label(f'“{entry.filename}” 첨부파일을 삭제할까요?').classes('break-all')
                with ui.row():
                    ui.button('취소', on_click=lambda: confirm.submit(False)).props('flat')
                    ui.button('삭제 확인', on_click=lambda: confirm.submit(True)).props('color=negative')
            try:
                if not await confirm:
                    return
            finally:
                confirm.delete()
            await run.io_bound(self.repository.delete, entry.id)
            await self.refresh()
            ui.notify('첨부파일을 삭제했습니다.', type='positive')


class AttachmentButton(ui.button):
    def __init__(self, database, kind, record_id=None):
        self.repository = DraftAttachments(database, kind, record_id)
        self.lock = asyncio.Lock()
        self.opened = False
        self.view = None
        super().__init__('파일 첨부', icon='attach_file', on_click=self.show)
        self.props('outline')

    @property
    def pending(self):
        return self.repository.pending

    async def save_record(self, function, *args):
        """파일 저장 실패도 일지 저장 실패로 처리하고 재시도할 파일을 보존한다."""
        self.disable()
        try:
            async with self.lock:
                if self.repository.closed:
                    raise DatabaseError('닫힌 일지는 저장할 수 없습니다.')
                attachments = tuple(self.repository.files.values())
                kwargs = {'attachments': attachments} if attachments else {}
                saved = await run.io_bound(function, *args, **kwargs)
                self.repository.record_id = saved.id
                self.repository.files.clear()
                return saved
        finally:
            if not self.is_deleted:
                self.enable()

    async def show(self):
        if self.opened or not self.enabled:
            return
        self.opened = True
        try:
            self.view = AttachmentView(self.repository, self.lock)
            with ui.context.client.content:
                self.view.build()
            self.view.dialog.open()
            async with self.view.operation():
                await self.view.refresh()
            await self.view.dialog
        finally:
            self.opened = False
            if self.view is not None and not self.view.dialog.is_deleted:
                self.view.dialog.delete()
            self.view = None

    def _handle_delete(self):
        self.repository.discard()
        if self.view is not None and not self.view.dialog.is_deleted:
            self.view.dialog.submit(None)
            self.view.dialog.delete()
        super()._handle_delete()


def attachment_button(database, kind: str, record_id: int | None):
    return AttachmentButton(database, kind, record_id)
