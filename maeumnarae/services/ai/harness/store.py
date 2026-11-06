"""양식만 저장한다. 시험 입력/출력은 이 저장소의 인터페이스에 없다."""
import json
import uuid
from pathlib import Path
from pydantic import ValidationError
from maeumnarae.core.paths import RESOURCE_ROOT
from maeumnarae.core.settings_store import SettingsStore
from ..types import AIError
from .types import HarnessDefinition

MAX_BYTES = 64 * 1024


def parse_definition(raw: str | bytes) -> HarnessDefinition:
    if len(raw.encode('utf-8') if isinstance(raw, str) else raw) > MAX_BYTES:
        raise AIError('양식 파일은 64 KiB 이하여야 합니다.')
    try:
        return HarnessDefinition.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise AIError('양식의 버전·이름·항목을 확인하세요. 출력 항목은 중복 없이 1~8개여야 합니다.') from None


class HarnessStore:
    def __init__(self, directory: Path):
        resource = RESOURCE_ROOT / 'ai/harness/defaults.json'
        bundled = json.loads(resource.read_text(encoding='utf-8'))
        self.defaults = {d['id']: HarnessDefinition.model_validate(d) for d in bundled['definitions']}
        self.examples = bundled['examples']
        self.store = SettingsStore(directory / 'ai-harnesses.json')
        self.records = {}
        self.error = ''
        try:
            self.records = self._read(self.store.read())
        except (OSError, ValueError, TypeError, KeyError):
            self.error = '작업 양식 설정을 읽지 못했습니다. 원본 파일을 보존했습니다. ai-harnesses.json을 확인하세요.'

    def _read(self, data):
        if not data:
            return {}
        if set(data) != {'version', 'definitions'} or type(data['version']) is not int or data['version'] != 1:
            raise ValueError()
        records = {}
        for item in data['definitions']:
            definition = HarnessDefinition.model_validate(item)
            if definition.id in records or definition.id in self.defaults:
                raise ValueError()
            records[definition.id] = definition
        return records

    @property
    def all(self):
        return {**self.defaults, **self.records}

    def _change(self, operation):
        if self.error:
            raise AIError(self.error)
        def change(data):
            records = self._read(data)
            operation(records)
            data.clear()
            data.update(version=1, definitions=[d.model_dump() for d in records.values()])
            return records
        try:
            records = self.store.update(change)
        except (OSError, ValueError, TypeError, KeyError):
            raise AIError('작업 양식을 저장하지 못했습니다. 기존 파일은 보존됩니다.') from None
        self.records = records

    def save(self, definition):
        definition = parse_definition(definition.model_dump_json())
        if definition.id in self.defaults:
            raise AIError('기본 양식은 복제한 뒤 수정하세요.')
        self._change(lambda records: records.update({definition.id: definition}))
        return definition

    def duplicate(self, definition):
        copy = definition.model_copy(update={'id': 'h_' + uuid.uuid4().hex,
                                             'name': definition.name[:75] + ' 사본'}, deep=True)
        return self.save(copy)

    def delete(self, key):
        if key in self.defaults:
            raise AIError('기본 양식은 삭제할 수 없습니다.')
        self._change(lambda records: records.pop(key, None))
