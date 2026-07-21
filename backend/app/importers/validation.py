from __future__ import annotations

import re
from collections import Counter

from app.schemas.imports import ImportIssue, ParsedQuestion


def validate_questions(questions: list[ParsedQuestion] | tuple[ParsedQuestion, ...]) -> list[ImportIssue]:
    issues: list[ImportIssue] = []
    code_counts = Counter(question.code for question in questions)
    for code, count in code_counts.items():
        if count > 1:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="DUPLICATE_CODE",
                    message=f"题号 {code} 重复出现 {count} 次。",
                    question_code=code,
                )
            )

    numeric_codes = [int(question.code) for question in questions if question.code.isdigit()]
    if numeric_codes:
        expected = list(range(min(numeric_codes), max(numeric_codes) + 1))
        if numeric_codes != expected:
            issues.append(
                ImportIssue(
                    severity="warning",
                    code="NON_CONTIGUOUS_CODES",
                    message="题目编号不是连续递增序列，请确认选择范围是否完整。",
                )
            )

    for question in questions:
        required = (
            ("image1_prompt", question.image1_prompt, "MISSING_IMAGE1_PROMPT", "图1生图提示词为空。"),
            ("image2_prompt", question.image2_prompt, "MISSING_IMAGE2_PROMPT", "图2生图提示词为空。"),
            ("answer", question.answer, "MISSING_ANSWER", "答案为空。"),
        )
        for field_name, value, code, message in required:
            if not value.strip():
                issues.append(
                    ImportIssue(
                        severity="error",
                        code=code,
                        message=message,
                        question_code=question.code,
                        field=field_name,
                    )
                )

        if question.answer_length is not None and len(question.answer) != question.answer_length:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="ANSWER_LENGTH_MISMATCH",
                    message=(
                        f"答案字数标注为 {question.answer_length}，实际为 {len(question.answer)}。"
                    ),
                    question_code=question.code,
                    field="answer",
                )
            )

        blank_count = len(re.findall(r"[＿_]", question.image2_fill))
        if question.answer_length is not None and blank_count != question.answer_length:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="BLANK_COUNT_MISMATCH",
                    message=f"图2填空数为 {blank_count}，答案字数为 {question.answer_length}。",
                    question_code=question.code,
                    field="image2_fill",
                )
            )
    return issues

