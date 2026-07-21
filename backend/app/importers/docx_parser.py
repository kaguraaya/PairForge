from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.importers.base import (
    FIELD_MAP,
    QuestionBuilder,
    normalized_label,
    parse_title,
    source_hash,
)
from app.importers.validation import validate_questions
from app.schemas.imports import ImportIssue, ImportPreview, ParsedQuestion


def iter_body_blocks(document: DocumentObject) -> Iterator[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def parse_docx(path: Path) -> ImportPreview:
    document = Document(path)
    questions: list[ParsedQuestion] = []
    issues: list[ImportIssue] = []
    current: QuestionBuilder | None = None

    def finish_current() -> None:
        nonlocal current
        if current is not None:
            questions.append(current.build())
            current = None

    for block in iter_body_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            title = parse_title(text)
            if title:
                finish_current()
                code, title_text, priority = title
                current = QuestionBuilder(
                    code=code,
                    title=title_text,
                    priority_blind_test=priority,
                )
            elif current and text.startswith("制作检查"):
                current.quality_parts.append(text)
            continue

        if current is None:
            continue
        rows: list[tuple[str, str]] = []
        for row in block.rows:
            values = [cell.text.strip() for cell in row.cells]
            if len(values) >= 2 and values[0]:
                rows.append((normalized_label(values[0]), values[1].strip()))
        if not any(label in FIELD_MAP for label, _ in rows):
            continue
        for label, value in rows:
            if label in FIELD_MAP:
                current.set_field(label, value, issues)
            elif label:
                current.add_unknown_field(label, value, issues)

    finish_current()
    issues.extend(validate_questions(questions))
    if not questions:
        issues.append(
            ImportIssue(
                severity="error",
                code="NO_QUESTIONS_FOUND",
                message="未识别到形如 001｜题目名称 的题目标题。",
            )
        )
    return ImportPreview(
        source_name=path.name,
        source_sha256=source_hash(path),
        questions=tuple(questions),
        issues=tuple(issues),
    )

