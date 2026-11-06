"""전체 가중치를 읽지 않는 제한된 GGUF 메타데이터 검사."""
import struct
from pathlib import Path
from .types import AIError


def inspect_gguf(path: Path) -> dict:
    try:
        size = path.stat().st_size
        with path.open('rb') as stream:
            def read(n):
                if n < 0 or stream.tell() + n > min(size, 64 * 1024 * 1024):
                    raise ValueError()
                value = stream.read(n)
                if len(value) != n:
                    raise ValueError()
                return value

            def number(fmt):
                return struct.unpack('<' + fmt, read(struct.calcsize('<' + fmt)))[0]

            def string(keep=True):
                length = number('Q')
                data = read(length)
                return data.decode('utf-8') if keep else None

            def value(kind, keep=False, depth=0):
                if depth > 1:
                    raise ValueError()
                formats = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i',
                           6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
                if kind in formats:
                    return number(formats[kind])
                if kind == 8:
                    return string(keep)
                if kind == 9:
                    item_type, count = number('I'), number('Q')
                    if count > 2_000_000:
                        raise ValueError()
                    for _ in range(count):
                        value(item_type, depth=depth + 1)
                    return None
                raise ValueError()

            if read(4) != b'GGUF' or number('I') not in (2, 3):
                raise ValueError()
            tensors, count = number('Q'), number('Q')
            if not 0 < tensors < 1_000_000 or count > 100_000:
                raise ValueError()
            metadata = {}
            wanted = {'general.architecture', 'general.name', 'split.count', 'tokenizer.chat_template'}
            for _ in range(count):
                key = string()
                item = value(number('I'), key in wanted)
                if key in wanted:
                    metadata[key] = item
            architecture = metadata.get('general.architecture')
            text_architectures = {'exaone', 'exaone4', 'qwen3', 'qwen3moe', 'llama', 'qwen2', 'gemma', 'gemma2', 'phi3'}
            if (not isinstance(architecture, str) or architecture not in text_architectures
                    or metadata.get('split.count', 1) != 1
                    or not isinstance(metadata.get('tokenizer.chat_template'), str)):
                raise ValueError()
            return metadata
    except (OSError, ValueError, UnicodeError, struct.error, OverflowError):
        raise AIError('단일 파일 텍스트 생성용 GGUF와 채팅 템플릿을 확인해 주세요.') from None
