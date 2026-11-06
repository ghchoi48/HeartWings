"""UI와 추론 엔진 사이의 공개 타입."""
from dataclasses import dataclass, field
from typing import Literal


class AIError(RuntimeError):
    """민감 정보를 포함하지 않는 사용자 표시용 오류."""


@dataclass(frozen=True)
class AISettings:
    enabled: bool = False
    selected_model_id: str | None = None
    reasoning_enabled: bool = False


@dataclass(frozen=True)
class ModelRecord:
    id: str
    name: str
    path: str
    size: int
    managed: bool = False
    profile: str = 'generic'
    verified: bool = False
    sha256: str | None = None


@dataclass(frozen=True)
class AIStatus:
    state: str
    error: str = ''
    download_id: str | None = None
    downloaded: int = 0
    total: int = 0


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    max_tokens: int = 512
    reasoning_enabled: bool = False
    system_instruction: str | None = None
    output_schema: dict | None = None
    temperature: float = 0.6


@dataclass(frozen=True)
class GenerationEvent:
    kind: Literal['text', 'reasoning', 'done']
    text: str = ''


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    repo: str
    revision: str
    filename: str
    size: int
    sha256: str
    license: str
    license_url: str
    memory_gb: int
    profile: str
    description: str
    system_prompt: str = 'You are a helpful assistant. Respond in Korean.'
    template_kwargs: dict = field(default_factory=dict)
    chat_template_file: str | None = None

    @property
    def url(self) -> str:
        return f'https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}'
