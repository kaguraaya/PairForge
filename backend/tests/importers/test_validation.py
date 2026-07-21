from app.importers.validation import validate_questions
from app.schemas.imports import ParsedQuestion


def question(code: str = "001") -> ParsedQuestion:
    return ParsedQuestion(
        code=code,
        title="测试题",
        question_type="动漫名",
        difficulty="★★☆☆☆",
        answer_length=3,
        image1_prompt="图1",
        image1_clue="这是图1",
        image2_prompt="图2",
        image2_fill="这是 ＿ ＿ ＿",
        answer="测试题",
        pinyin="ce4 shi4 ti2",
        explanation="拆解",
    )


def test_validation_rejects_missing_prompt_and_duplicate_code() -> None:
    first = question()
    duplicate = question().model_copy(update={"image2_prompt": ""})

    issues = validate_questions([first, duplicate])

    codes = {issue.code for issue in issues}
    assert "DUPLICATE_CODE" in codes
    assert "MISSING_IMAGE2_PROMPT" in codes


def test_validation_reports_answer_blank_mismatch() -> None:
    invalid = question().model_copy(update={"image2_fill": "这是 ＿ ＿"})

    issues = validate_questions([invalid])

    assert any(issue.code == "BLANK_COUNT_MISMATCH" for issue in issues)
