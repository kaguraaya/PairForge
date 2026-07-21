from __future__ import annotations

import hashlib
import re

from app.importers.base import FIELD_MAP, QuestionBuilder, normalized_label, parse_title
from app.importers.validation import validate_questions
from app.schemas.imports import ImportIssue, ImportPreview, ParsedQuestion


INFO_LINE_RE = re.compile(r"^[-*]\s*(类型|难度|答案字数|出处)\s*[:：]\s*(.+)$")


def parse_markdown_text(source: str, source_name: str = "题库.md") -> ImportPreview:
    questions: list[ParsedQuestion] = []
    issues: list[ImportIssue] = []
    current: QuestionBuilder | None = None
    active_field: str | None = None
    active_lines: list[str] = []
    basic_parts: list[str] = []

    def flush_field() -> None:
        nonlocal active_field, active_lines
        if current and active_field:
            current.set_field(active_field, "\n".join(active_lines).strip(), issues)
        active_field = None
        active_lines = []

    def finish_current() -> None:
        nonlocal current, basic_parts
        flush_field()
        if current:
            if basic_parts:
                current.set_field("基本信息", " ｜ ".join(basic_parts), issues)
            questions.append(current.build())
        current = None
        basic_parts = []

    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## ") and not line.startswith("### "):
            title = parse_title(line[3:].strip())
            if title:
                finish_current()
                code, title_text, priority = title
                current = QuestionBuilder(code=code, title=title_text, priority_blind_test=priority)
            continue
        if current is None:
            continue
        if line.startswith("### "):
            flush_field()
            label = normalized_label(line[4:].strip())
            if label in FIELD_MAP:
                active_field = label
            else:
                active_field = label
                current.add_unknown_field(label, "", issues)
            continue
        info_match = INFO_LINE_RE.match(line.strip())
        if info_match and active_field is None:
            basic_parts.append(f"{info_match.group(1)}：{info_match.group(2).strip()}")
            continue
        if active_field is not None:
            active_lines.append(line)

    finish_current()
    issues.extend(validate_questions(questions))
    if not questions:
        issues.append(
            ImportIssue(
                severity="error",
                code="NO_QUESTIONS_FOUND",
                message="Markdown 中未识别到题目标题。",
            )
        )
    return ImportPreview(
        source_name=source_name,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        questions=tuple(questions),
        issues=tuple(issues),
    )

