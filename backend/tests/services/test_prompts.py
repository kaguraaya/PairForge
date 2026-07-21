from app.services.prompts import compose_prompt


def test_empty_suffix_does_not_change_prompt() -> None:
    assert compose_prompt("原始提示词", "") == "原始提示词"
    assert compose_prompt("原始提示词", "   ") == "原始提示词"


def test_suffix_is_appended_with_clear_boundary() -> None:
    assert compose_prompt("原始提示词", "保持水彩风") == (
        "原始提示词\n\n【全局补充要求】\n保持水彩风"
    )
