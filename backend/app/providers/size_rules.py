from __future__ import annotations

import re


SEEDREAM_5_LITE_MODELS = {"doubao-seedream-5-0-lite-260128"}
SEEDREAM_5_LITE_MIN_PIXELS = 2_560 * 1_440
SEEDREAM_5_LITE_MAX_PIXELS = 4_096 * 4_096

# Earlier app builds exposed these ratio presets. They are below Seedream 5.0
# Lite's documented minimum total pixel count, so keep old projects usable by
# upgrading them to the nearest equivalent ratio before validation or sending.
SEEDREAM_5_LITE_LEGACY_SIZES = {
    "2048x1536": "2304x1728",
    "1536x2048": "1728x2304",
    "2048x1152": "2560x1440",
    "1152x2048": "1440x2560",
}

_EXPLICIT_SIZE = re.compile(r"^(\d{2,5})x(\d{2,5})$", re.IGNORECASE)
_RESOLUTION_LEVELS = {"2K", "3K", "4K"}


def is_seedream_5_lite(provider: str, model_id: str) -> bool:
    return provider == "volcengine" and model_id in SEEDREAM_5_LITE_MODELS


def normalize_image_size(provider: str, model_id: str, size: str) -> str:
    normalized = size.strip()
    if not is_seedream_5_lite(provider, model_id):
        return normalized
    resolution = normalized.upper()
    if resolution in _RESOLUTION_LEVELS:
        return resolution
    explicit = normalized.lower()
    return SEEDREAM_5_LITE_LEGACY_SIZES.get(explicit, explicit)


def normalize_generation_config(
    provider: str,
    model_id: str,
    config: dict[str, object] | None,
) -> dict[str, object]:
    normalized = dict(config or {})
    size = normalized.get("size")
    if isinstance(size, str):
        normalized["size"] = normalize_image_size(provider, model_id, size)
    return normalized


def seedream_5_lite_size_error(provider: str, model_id: str, size: str) -> str | None:
    if not is_seedream_5_lite(provider, model_id):
        return None
    normalized = normalize_image_size(provider, model_id, size)
    if normalized in _RESOLUTION_LEVELS:
        return None
    match = _EXPLICIT_SIZE.fullmatch(normalized)
    if not match:
        return (
            "Seedream 5.0 Lite 尺寸应填写 2K、3K、4K 或“宽x高”"
            "（例如 2304x1728）"
        )
    width, height = (int(value) for value in match.groups())
    pixels = width * height
    if not SEEDREAM_5_LITE_MIN_PIXELS <= pixels <= SEEDREAM_5_LITE_MAX_PIXELS:
        return (
            "Seedream 5.0 Lite 显式尺寸的总像素必须在 3,686,400 到 "
            f"16,777,216 之间；当前 {normalized} 为 {pixels:,} 像素"
        )
    ratio = width / height
    if not 1 / 16 <= ratio <= 16:
        return "Seedream 5.0 Lite 的宽高比必须在 1:16 到 16:1 之间"
    return None
