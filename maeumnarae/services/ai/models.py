"""검증된 추천 다운로드와 외부 GGUF 참조 관리."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import httpx

from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.core.settings_store import SettingsStore
from .gguf import inspect_gguf
from .types import AIError, CatalogModel, ModelRecord


def catalog() -> tuple[CatalogModel, ...]:
    return tuple(CatalogModel(**item) for item in json.loads(
        (RESOURCE_ROOT / 'ai/models.json').read_text(encoding='utf-8')))


def supports_reasoning(record: ModelRecord | None) -> bool:
    return record is not None and any(
        item.profile == record.profile and 'enable_thinking' in item.template_kwargs
        for item in catalog())


class ModelManager:
    def __init__(self, directory: Path):
        self.directory = directory / 'ai-models'
        self.store = SettingsStore(directory / 'ai-models.json')
        self.error = ''
        self.records = {}
        try:
            for item in self.store.read().get('models', []):
                record = ModelRecord(**item)
                if (not isinstance(record.path, str) or not isinstance(record.size, int)
                        or type(record.managed) is not bool or record.profile not in {'generic', 'exaone', 'exaone4', 'qwen3'}):
                    raise ValueError()
                self.records[record.id] = record
        except (OSError, ValueError, TypeError, AttributeError):
            self.records = {}
            self.error = '모델 목록을 읽지 못했습니다. ai-models.json을 확인해 주세요.'

    def _save(self, records):
        try:
            self.store.update(lambda data: data.update(models=[asdict(r) for r in records.values()]))
        except (OSError, ValueError, TypeError):
            raise AIError('모델 목록을 저장하지 못했습니다. 설정 파일과 폴더 권한을 확인해 주세요.') from None
        self.records = records

    def register(self, path: Path, metadata=None) -> ModelRecord:
        path = path.expanduser().resolve(strict=True)
        metadata = metadata if metadata is not None else inspect_gguf(path)
        for record in self.records.values():
            if Path(record.path).resolve() == path:
                return record
        architecture = metadata['general.architecture']
        profile = {'exaone': 'exaone', 'exaone4': 'exaone4', 'qwen3': 'qwen3'}.get(architecture, 'generic')
        record = ModelRecord(uuid.uuid4().hex, path.name, str(path), path.stat().st_size, profile=profile)
        self._save({**self.records, record.id: record})
        return record

    def mark_verified(self, model_id):
        record = self.records[model_id]
        self._save({**self.records, model_id: replace(record, verified=True)})

    def remove(self, model_id):
        record = self.records[model_id]
        # 설정 파일이 변경되어도 관리 폴더 밖의 원본은 삭제하지 않는다.
        path = Path(record.path)
        if record.managed and (path.is_symlink() or path.resolve().parent != self.directory.resolve()):
            raise AIError('관리 폴더 밖의 파일은 삭제할 수 없습니다.')
        remaining = {key: value for key, value in self.records.items() if key != model_id}
        if record.managed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                raise AIError('모델 파일을 삭제하지 못했습니다. 사용 여부와 권한을 확인해 주세요.') from None
        self._save(remaining)

    async def download(self, item: CatalogModel, progress, client=None):
        if item.id in self.records:
            raise AIError('이미 등록된 모델입니다. 삭제 후 다시 다운로드해 주세요.')
        self.directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.directory).free < item.size + 64 * 1024 * 1024:
            raise AIError('모델 다운로드를 위한 디스크 공간이 부족합니다.')
        destination = self.directory / item.filename
        temporary = self.directory / (uuid.uuid4().hex + '.part')
        own_client = client is None
        client = client or httpx.AsyncClient(follow_redirects=True, timeout=60)
        try:
            digest = hashlib.sha256()
            received = 0
            async with client.stream('GET', item.url) as response:
                response.raise_for_status()
                with temporary.open('xb') as stream:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        received += len(chunk)
                        if received > item.size:
                            raise AIError('모델 파일 크기가 공식 배포 정보와 다릅니다.')
                        stream.write(chunk)
                        digest.update(chunk)
                        progress(received, item.size)
                        await asyncio.sleep(0)
                    stream.flush()
                    os.fsync(stream.fileno())
            if received != item.size or digest.hexdigest() != item.sha256:
                raise AIError('모델 무결성 검증에 실패했습니다. 다시 다운로드해 주세요.')
            await asyncio.to_thread(inspect_gguf, temporary)
            temporary.replace(destination)
            record = ModelRecord(item.id, item.name, str(destination.resolve()), item.size,
                                 managed=True, profile=item.profile, sha256=item.sha256)
            self._save({**self.records, record.id: record})
            return record
        except (httpx.HTTPError, OSError):
            raise AIError('모델을 다운로드하지 못했습니다. 네트워크·디스크 공간·권한을 확인해 주세요.') from None
        finally:
            temporary.unlink(missing_ok=True)
            if own_client:
                await client.aclose()
