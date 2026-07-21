from __future__ import annotations

from pathlib import Path

from app.importers.doc_converter import convert_doc_to_docx
from app.importers.docx_parser import parse_docx
from app.importers.markdown_parser import parse_markdown_text
from app.schemas.imports import ImportPreview


def parse_question_bank(path: Path, conversion_dir: Path | None = None) -> ImportPreview:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return parse_docx(path)
    if suffix in {".md", ".markdown"}:
        return parse_markdown_text(path.read_text(encoding="utf-8-sig"), path.name)
    if suffix == ".doc":
        target = convert_doc_to_docx(path, conversion_dir or path.parent)
        return parse_docx(target)
    raise ValueError(f"不支持的题库格式：{suffix or '无扩展名'}")

