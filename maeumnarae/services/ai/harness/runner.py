import time
from ..types import AIError
from .context import build_request
from .store import parse_definition
from .types import HarnessRunResult, ValidationIssue
from .validators import validate_output


async def run(definition, note, generate):
    definition = parse_definition(definition.model_dump_json())
    note = note.strip()
    if not note or len(note) > 12000:
        raise AIError('시험 입력은 1~12,000자로 작성하세요.')
    started = time.monotonic()
    for attempt in range(2):
        raw = await generate(build_request(definition, note, retry=bool(attempt)))
        try:
            fields, issues = validate_output(raw, definition, note)
        except ValueError:
            if attempt == 0:
                continue
            return HarnessRunResult(fields=[], issues=[ValidationIssue(code='invalid_format',
                message='두 번의 생성 모두 형식 검사에 실패했습니다. 양식을 단순화하거나 모델을 변경하세요.')],
                raw_json=raw, elapsed_seconds=time.monotonic() - started,
                retries=1, format_errors=2, format_valid=False)
        return HarnessRunResult(fields=fields, issues=issues, raw_json=raw,
            elapsed_seconds=time.monotonic() - started, retries=attempt,
            format_errors=attempt, format_valid=True)
