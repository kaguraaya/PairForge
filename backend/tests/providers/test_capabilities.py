import pytest

from app.domain.enums import GenerationStage, OutputSemantics
from app.providers.registry import model_registry


def test_seedream_uses_variable_multi_output_semantics() -> None:
    caps = model_registry.get("volcengine", "doubao-seedream-5-0-lite-260128")

    assert caps.supports_text_to_image is True
    assert caps.supports_image_edit is True
    assert caps.single_output_semantics is OutputSemantics.FIXED
    assert caps.multiple_output_semantics is OutputSemantics.MAXIMUM
    assert caps.max_outputs(GenerationStage.IMAGE1) == 15
    assert caps.max_outputs(GenerationStage.IMAGE2) == 14


def test_qwen_and_wan_capabilities_are_not_mixed() -> None:
    qwen = model_registry.get("alibaba", "qwen-image-2.0")
    wan = model_registry.get("alibaba", "wan2.7-image")

    assert qwen.max_outputs(GenerationStage.IMAGE2) == 6
    assert wan.max_outputs(GenerationStage.IMAGE2) == 4
    assert qwen.multiple_output_semantics is OutputSemantics.EXACT
    assert wan.multiple_output_semantics is OutputSemantics.EXACT
    assert qwen.default_size == "2368*1728"
    assert wan.default_size == "2048*1536"


def test_registry_rejects_unknown_model() -> None:
    with pytest.raises(KeyError):
        model_registry.get("alibaba", "not-a-real-model")


def test_other_current_seedream_models_are_available() -> None:
    seedream_45 = model_registry.get("volcengine", "doubao-seedream-4-5-251128")
    seedream_40 = model_registry.get("volcengine", "doubao-seedream-4-0-250828")
    assert seedream_45.supports_image_edit is True
    assert seedream_40.supports_image_edit is True
    assert seedream_45.max_outputs(GenerationStage.IMAGE2) == 14
    assert seedream_40.max_outputs(GenerationStage.IMAGE1) == 15
    assert str(seedream_45.unit_price_cny) == "0.25"
    assert str(seedream_40.unit_price_cny) == "0.20"
