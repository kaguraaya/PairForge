from __future__ import annotations

import re


SEEDREAM_SIZE_SPECS = {
    "doubao-seedream-5-0-lite-260128": {
        "display_name": "Seedream 5.0 Lite",
        "levels": frozenset({"2K", "3K", "4K"}),
        "min_pixels": 2_560 * 1_440,
        "max_pixels": 4_096 * 4_096,
    },
    "doubao-seedream-4-5-251128": {
        "display_name": "Seedream 4.5",
        "levels": frozenset({"2K", "4K"}),
        "min_pixels": 2_560 * 1_440,
        "max_pixels": 4_096 * 4_096,
    },
}

# Earlier app builds exposed these ratio presets for Seedream. They are below
# the current 5.0 Lite and 4.5 minimum pixel count, so keep old projects usable
# by upgrading them to the official 2K ratio mapping before validation or sending.
SEEDREAM_LEGACY_SIZES = {
    "2048x1536": "2304x1728",
    "1536x2048": "1728x2304",
    "2048x1152": "2848x1600",
    "1152x2048": "1600x2848",
}

_EXPLICIT_SIZE = re.compile(r"^(\d{2,5})x(\d{2,5})$", re.IGNORECASE)
_RESOLUTION_LEVEL = re.compile(r"^\d{1,2}K$", re.IGNORECASE)


def seedream_size_spec(provider: str, model_id: str) -> dict[str, object] | None:
    if provider != "volcengine":
        return None
    return SEEDREAM_SIZE_SPECS.get(model_id)


def normalize_image_size(provider: str, model_id: str, size: str) -> str:
    normalized = size.strip()
    spec = seedream_size_spec(provider, model_id)
    if spec is None:
        return normalized
    resolution = normalized.upper()
    if resolution in spec["levels"]:
        return resolution
    explicit = normalized.lower()
    return SEEDREAM_LEGACY_SIZES.get(explicit, explicit)


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


def seedream_size_error(provider: str, model_id: str, size: str) -> str | None:
    spec = seedream_size_spec(provider, model_id)
    if spec is None:
        return None
    normalized = normalize_image_size(provider, model_id, size)
    levels = spec["levels"]
    if normalized in levels:
        return None
    display_name = str(spec["display_name"])
    if _RESOLUTION_LEVEL.fullmatch(normalized):
        choices = "、".join(sorted(levels))
        return f"{display_name} 分辨率档位仅支持 {choices}"
    match = _EXPLICIT_SIZE.fullmatch(normalized)
    if not match:
        return (
            f"{display_name} 尺寸应填写支持的分辨率档位或“宽x高”"
            "（例如 2304x1728）"
        )
    width, height = (int(value) for value in match.groups())
    pixels = width * height
    min_pixels = int(spec["min_pixels"])
    max_pixels = int(spec["max_pixels"])
    if not min_pixels <= pixels <= max_pixels:
        return (
            f"{display_name} 显式尺寸的总像素必须在 {min_pixels:,} 到 "
            f"{max_pixels:,} 之间；当前 {normalized} 为 {pixels:,} 像素"
        )
    ratio = width / height
    if not 1 / 16 <= ratio <= 16:
        return f"{display_name} 的宽高比必须在 1:16 到 16:1 之间"
    return None
