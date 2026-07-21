import re
import unicodedata

from app.domain.enums import GenerationStage

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_component(value: str, maximum: int = 80) -> str:
    cleaned = _INVALID.sub("_", unicodedata.normalize("NFC", value)).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned) or "未命名"
    if cleaned.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:maximum].rstrip(" .")


def candidate_name(
    code: str,
    stage: GenerationStage,
    request_index: int,
    output_index: int,
    asset_id: str,
    extension: str = ".png",
) -> str:
    stage_label = "Q1" if stage is GenerationStage.IMAGE1 else "Q2"
    return (
        f"{safe_component(code, 20)}__{stage_label}__REQ{request_index:02d}__"
        f"OUT{output_index:02d}__{asset_id[:8]}{extension.lower()}"
    )


def final_name(code: str, answer: str, stage_number: int, extension: str = ".png") -> str:
    return f"{safe_component(code, 20)}__{safe_component(answer)}__{stage_number:02d}{extension.lower()}"

