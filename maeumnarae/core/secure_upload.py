"""크기·동시 수신을 제한하고 평문 디스크 스풀 없이 처리하는 업로드."""

import asyncio
import inspect

from fastapi import HTTPException, Request
from nicegui import app, ui, helpers
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.events import UiEventArguments, UploadEventArguments, MultiUploadEventArguments
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from maeumnarae.core.upload_limits import MAX_BACKUP_BYTES

MULTIPART_OVERHEAD = 64 * 1024
_upload_active = False


class UploadTooLarge(MultiPartException):
    pass


class MemoryMultipartParser(MultiPartParser):
    """요청 전체와 파일 크기를 모두 제한하여 SpooledTemporaryFile의 디스크 전환을 막는다."""

    def __init__(self, headers, stream, *, limit, max_files=1):
        self.limit = limit
        total_limit = min(limit * max_files, MAX_BACKUP_BYTES)
        self.part_bytes = 0
        self.spool_max_size = limit + 1

        async def bounded_stream():
            total = 0
            async for chunk in stream:
                total += len(chunk)
                if total > total_limit + MULTIPART_OVERHEAD:
                    raise UploadTooLarge('업로드 크기 제한을 초과했습니다.')
                # 파서의 한 번 처리량도 제한한다.
                for offset in range(0, len(chunk), 64 * 1024):
                    yield chunk[offset:offset + 64 * 1024]

        super().__init__(headers, bounded_stream(), max_files=max_files, max_fields=0)

    def on_part_begin(self):
        self.part_bytes = 0
        super().on_part_begin()

    def on_part_data(self, data, start, end):
        self.part_bytes += end - start
        if self.part_bytes > self.limit:
            raise UploadTooLarge('업로드 크기 제한을 초과했습니다.')
        super().on_part_data(data, start, end)

    async def parse(self):
        try:
            return await super().parse()
        except BaseException:
            # 연결 중단/취소 등 MultiPartException 이외의 실패도 정리한다.
            for stream in self._files_to_close_on_error:
                stream.close()
            raise


async def receive_memory_uploads(request: Request, limit: int, max_files: int = 1) -> list[SmallFileUpload]:
    total_limit = min(limit * max_files, MAX_BACKUP_BYTES)
    if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
        raise HTTPException(400, 'multipart/form-data 형식으로 업로드해 주세요.')
    length = request.headers.get('content-length')
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(400, '잘못된 Content-Length입니다.') from None
        if size < 0:
            raise HTTPException(400, '잘못된 Content-Length입니다.')
        if size > total_limit + MULTIPART_OVERHEAD:
            raise HTTPException(413, '업로드 크기 제한을 초과했습니다.')
    parser = MemoryMultipartParser(request.headers, request.stream(), limit=limit, max_files=max_files)
    try:
        form = await asyncio.wait_for(parser.parse(), timeout=120)
        try:
            files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
            if not 1 <= len(files) <= max_files:
                raise HTTPException(400, '업로드할 파일 수를 확인해 주세요.')
            uploaded = []
            for file in files:
                # NiceGUI 변환 경로의 별도 평문 임시파일을 만들지 않는다.
                content = await file.read(limit + 1)
                if len(content) > limit:
                    raise HTTPException(413, '업로드 크기 제한을 초과했습니다.')
                name = (file.filename or '').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
                uploaded.append(SmallFileUpload(name, file.content_type or '', content))
                await file.close()
            return uploaded
        finally:
            await form.close()
    except UploadTooLarge:
        raise HTTPException(413, '업로드 크기 제한을 초과했습니다.') from None
    except MultiPartException:
        raise HTTPException(400, '업로드 형식이 올바르지 않습니다.') from None
    except TimeoutError:
        raise HTTPException(408, '업로드 시간이 초과되었습니다.') from None


async def receive_memory_upload(request: Request, limit: int) -> SmallFileUpload:
    return (await receive_memory_uploads(request, limit))[0]


class SecureUpload(ui.upload):
    def __init__(self, *, max_file_size: int, **kwargs):
        if not 0 < max_file_size <= MAX_BACKUP_BYTES:
            raise ValueError('업로드 크기 제한을 지정해 주세요.')
        max_files = kwargs.setdefault('max_files', 10 if kwargs.get('multiple') else 1)
        super().__init__(max_file_size=max_file_size, **kwargs)
        if kwargs.get('multiple'):
            self._props['batch'] = True
            self._props['max-total-size'] = min(max_file_size * max_files, MAX_BACKUP_BYTES)
        # 부모가 등록한 무제한 form()/디스크 스풀 경로를 교체한다.
        app.remove_route(self._registered_url)

        @app.post(self._registered_url, include_in_schema=False)
        async def upload_route(request: Request):
            global _upload_active
            if self.is_ignoring_events:
                raise HTTPException(403, 'Upload is disabled or hidden')
            if _upload_active:
                raise HTTPException(429, '다른 파일을 처리 중입니다. 완료 후 다시 시도해 주세요.')
            _upload_active = True
            try:
                for handler in self._begin_upload_handlers:
                    await self._call_handler(handler, UiEventArguments(sender=self, client=self.client))
                files = await receive_memory_uploads(request, max_file_size, max_files)
                if self.is_ignoring_events:
                    raise HTTPException(403, 'Upload is disabled or hidden')
                for file in files:
                    for handler in self._upload_handlers:
                        await self._call_handler(handler, UploadEventArguments(sender=self, client=self.client, file=file))
                for handler in self._multi_upload_handlers:
                    await self._call_handler(handler, MultiUploadEventArguments(sender=self, client=self.client, files=files))
                return {'upload': 'success'}
            finally:
                _upload_active = False

    async def _call_handler(self, handler, event):
        # 업로드 처리가 끝날 때까지 수신 슬롯을 유지한다. UI 작업에도 올바른 슬롯을 제공한다.
        with self.parent_slot or self.client.layout.default_slot:
            result = handler(event) if helpers.expects_arguments(handler) else handler()
            if inspect.isawaitable(result):
                await result
