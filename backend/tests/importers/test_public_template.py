from pathlib import Path
from zipfile import ZipFile

from app.importers.docx_parser import parse_docx


TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "PairForge题库模板.docx"


def test_public_docx_template_is_importable_and_contains_only_placeholders() -> None:
    preview = parse_docx(TEMPLATE)

    assert [question.code for question in preview.questions] == ["001", "002"]
    assert preview.error_count == 0
    assert all(question.image1_prompt and question.image2_prompt for question in preview.questions)
    assert [question.answer for question in preview.questions] == ["示例答案", "占位答案"]
    with ZipFile(TEMPLATE) as package:
        names = package.namelist()
        xml_text = "\n".join(
            package.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".xml", ".rels"))
        )
    assert "青之驱魔师" not in xml_text
    assert not any(name.startswith("customXml/") for name in names)
