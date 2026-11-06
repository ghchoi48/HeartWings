"""사용자가 편집할 수 있는 선언적 작업 양식. 실행 가능한 설정은 받지 않는다."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class HarnessField(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')
    name: str = Field(min_length=1, max_length=80)
    instruction: str = Field(default='', max_length=2000)
    evidence_required: bool = True


class HarnessDefinition(StrictModel):
    version: Literal[1] = 1
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)
    instruction: str = Field(default='', max_length=4000)
    style: str = Field(default='객관적이고 간결한 한국어', max_length=500)
    fields: list[HarnessField] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def unique_fields(self):
        if not self.name.strip() or any(not f.name.strip() for f in self.fields):
            raise ValueError('이름을 입력하세요.')
        if len({f.id for f in self.fields}) != len(self.fields):
            raise ValueError('항목 ID가 중복되었습니다.')
        return self


class DraftField(StrictModel):
    id: str
    text: str = Field(min_length=1, max_length=12000)
    evidence: list[str] = Field(max_length=20)


class Draft(StrictModel):
    fields: list[DraftField] = Field(min_length=1, max_length=8)


class ValidationIssue(StrictModel):
    code: str
    message: str
    field_id: str = ''


class HarnessRunResult(StrictModel):
    fields: list[DraftField]
    issues: list[ValidationIssue]
    raw_json: str
    elapsed_seconds: float
    retries: int
    format_errors: int
    format_valid: bool
    needs_review: bool = True
