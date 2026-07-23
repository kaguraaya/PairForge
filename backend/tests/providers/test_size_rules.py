from app.providers.size_rules import (
    normalize_generation_config,
    normalize_image_size,
    seedream_size_error,
)


PROVIDER = "volcengine"
MODEL = "doubao-seedream-5-0-lite-260128"


def test_seedream_5_lite_upgrades_legacy_presets_without_changing_ratio() -> None:
    assert normalize_image_size(PROVIDER, MODEL, "2048x1536") == "2304x1728"
    assert normalize_image_size(PROVIDER, MODEL, "1536X2048") == "1728x2304"
    assert normalize_image_size(PROVIDER, MODEL, "2048x1152") == "2848x1600"
    assert normalize_generation_config(
        PROVIDER, MODEL, {"size": " 1152x2048 ", "watermark": False}
    ) == {"size": "1600x2848", "watermark": False}


def test_seedream_5_lite_accepts_documented_resolution_levels_and_pixel_range() -> None:
    for size in ("2K", "3k", "4K", "2048x2048", "2304x1728", "2560x1440"):
        assert seedream_size_error(PROVIDER, MODEL, size) is None


def test_seedream_5_lite_rejects_other_too_small_or_malformed_sizes() -> None:
    too_small = seedream_size_error(PROVIDER, MODEL, "1024x1024")
    malformed = seedream_size_error(PROVIDER, MODEL, "2048*2048")

    assert too_small and "3,686,400" in too_small and "1,048,576" in too_small
    assert malformed and "宽x高" in malformed


def test_seedream_4_5_uses_its_documented_levels_range_and_migration() -> None:
    model = "doubao-seedream-4-5-251128"

    assert normalize_image_size(PROVIDER, model, "2048x1536") == "2304x1728"
    assert normalize_image_size(PROVIDER, model, "2048x1152") == "2848x1600"
    for size in ("2k", "4K", "2048x2048", "2304x1728", "2848x1600", "6240x2656"):
        assert seedream_size_error(PROVIDER, model, size) is None

    unsupported_level = seedream_size_error(PROVIDER, model, "3K")
    too_small = seedream_size_error(PROVIDER, model, "1500x1500")
    too_large = seedream_size_error(PROVIDER, model, "4097x4097")
    extreme_ratio = seedream_size_error(PROVIDER, model, "8500x500")

    assert unsupported_level == "Seedream 4.5 分辨率档位仅支持 2K、4K"
    assert too_small and "3,686,400" in too_small
    assert too_large and "16,777,216" in too_large
    assert extreme_ratio and "1:16" in extreme_ratio


def test_size_rules_do_not_mix_other_models_or_providers() -> None:
    assert normalize_image_size("alibaba", "qwen-image-2.0", "2048*1536") == "2048*1536"
    assert (
        normalize_image_size(PROVIDER, "doubao-seedream-4-0-250828", "2048x1536")
        == "2048x1536"
    )
