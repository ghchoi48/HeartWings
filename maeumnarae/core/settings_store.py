"""화면 설정과 위젯이 공유하는 JSON 파일의 원자적 읽기·수정·저장."""

import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

_LOCK = RLock()


class SettingsStore:
    def __init__(self, path: Path | None):
        self.path = path
        self._memory = {}

    def _read(self) -> dict:
        if self.path is None:
            return deepcopy(self._memory)
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('설정 파일은 JSON 객체여야 합니다.')
        return data

    def update(self, change):
        """최신 파일을 읽고 필요한 키만 변경한다. 실패하면 기존 파일을 보존한다."""
        with _LOCK:
            data = self._read()
            result = change(data)
            if self.path is None:
                self._memory = deepcopy(data)
                return deepcopy(result)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                        prefix=self.path.name + '.', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(data, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return deepcopy(result)

    def read(self) -> dict:
        with _LOCK:
            return self._read()
