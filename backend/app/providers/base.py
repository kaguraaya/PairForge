from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.domain.enums import GenerationStage, OutputSemantics


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    provider: str
    model: str
    display_name: str
    supports_text_to_image: bool
    supports_image_edit: bool
    min_outputs: int
    max_text_outputs: int
    max_edit_outputs: int
    default_size: str
    single_output_semantics: OutputSemantics
    multiple_output_semantics: OutputSemantics
    unit_price_cny: Decimal
    price_checked_on: str
    documentation_url: str

    def max_outputs(self, stage: GenerationStage) -> int:
        if stage is GenerationStage.IMAGE1:
            return self.max_text_outputs
        if stage is GenerationStage.IMAGE2:
            return self.max_edit_outputs
        raise ValueError(f"Unsupported generation stage: {stage}")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    api_key: str
    base_url: str
    workspace_id: str | None = None
    api_mode: str = "standard"


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    model: str
    prompt: str
    stage: GenerationStage
    requested_outputs: int = 1
    size: str | None = None
    reference_image: str | None = None
    watermark: bool = False
    seed: int | None = None
    guidance_scale: float | None = None
    prompt_extend: bool | None = None
    thinking_mode: bool | None = None


@dataclass(frozen=True, slots=True)
class ImageSource:
    url: str | None = None
    b64_json: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    images: tuple[ImageSource, ...]
    provider_request_id: str | None = None
    usage: dict[str, object] = field(default_factory=dict)


class ImageProvider(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
