from app.providers.size_rules import (
    normalize_generation_config,
    normalize_image_size,
    seedream_5_lite_size_error,
)


PROVIDER = "volcengine"
MODEL = "doubao-seedream-5-0-lite-260128"


def test_seedream_5_lite_upgrades_legacy_presets_without_changing_ratio() -> None:
    assert normalize_image_size(PROVIDER, MODEL, "2048x1536") == "2304x1728"
    assert normalize_image_size(PROVIDER, MODEL, "1536X2048") == "1728x2304"
    assert normalize_image_size(PROVIDER, MODEL, "2048x1152") == "2560x1440"
    assert normalize_generation_config(
        PROVIDER, MODEL, {"size": " 1152x2048 ", "watermark": False}
    ) == {"size": "1440x2560", "watermark": False}


def test_seedream_5_lite_accepts_documented_resolution_levels_and_pixel_range() -> None:
    for size in ("2K", "3k", "4K", "2048x2048", "2304x1728", "2560x1440"):
        assert seedream_5_lite_size_error(PROVIDER, MODEL, size) is None


def test_seedream_5_lite_rejects_other_too_small_or_malformed_sizes() -> None:
    too_small = seedream_5_lite_size_error(PROVIDER, MODEL, "1024x1024")
    malformed = seedream_5_lite_size_error(PROVIDER, MODEL, "2048*2048")

    assert too_small and "3,686,400" in too_small and "1,048,576" in too_small
    assert malformed and "宽x高" in malformed


def test_size_rules_do_not_mix_other_models_or_providers() -> None:
    assert normalize_image_size("alibaba", "qwen-image-2.0", "2048*1536") == "2048*1536"
    assert (
        normalize_image_size(PROVIDER, "doubao-seedream-4-0-250828", "2048x1536")
        == "2048x1536"
    )
