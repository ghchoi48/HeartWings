"""모든 일지가 공유하는 파일 첨부·다운로드·삭제 창."""
import asyncio
from contextlib import asynccontextmanager

from nicegui import run, ui

from maeumnarae.core.database import DatabaseError
from maeumnarae.repositories.attachment_repo import AttachmentRepository, MAX_ATTACHMENT_BYTES


class AttachmentView:
    def __init__(self, repository: AttachmentRepository):
        self.repository = repository
        self.lock = asyncio.Lock()
        self.pending = 0

    def build(self):
        with ui.dialog().props('persistent') as self.dialog, ui.card().classes('w-full max-w-2xl p-6 gap-4'):
            ui.label('일지 첨부파일').classes('text-2xl font-bold')
            ui.label('파일당 최대 20MB · 첨부와 삭제는 즉시 저장됩니다. 일지 삭제 시 첨부파일도 함께 삭제됩니다.').classes('text-sm text-slate-500')
            self.upload = ui.upload(label='파일 선택 또는 끌어놓기', auto_upload=True, multiple=True,
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
            ui.notify('첨부파일을 저장했습니다.', type='positive')

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


def attachment_button(database, kind: str, record_id: int | None):
    if record_id is None:
        ui.label('일지를 저장한 후 목록의 파일 첨부 버튼에서 파일을 추가할 수 있습니다.').classes('text-sm text-slate-500')
        return
    opened = False

    async def show():
        nonlocal opened
        if opened:
            return
        opened = True
        view = None
        try:
            view = AttachmentView(AttachmentRepository(database, kind, record_id))
            with ui.context.client.content:
                view.build()
            view.dialog.open()
            async with view.operation():
                await view.refresh()
            await view.dialog
        finally:
            opened = False
            if view is not None and not view.dialog.is_deleted:
                view.dialog.delete()

    return ui.button('파일 첨부', icon='attach_file', on_click=show).props('outline')
