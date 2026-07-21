import os
from pathlib import Path

import pytest

from app.importers.docx_parser import parse_docx


@pytest.mark.skipif(not os.getenv("REFERENCE_DOCX"), reason="REFERENCE_DOCX not configured")
def test_reference_docx_has_100_complete_questions() -> None:
    preview = parse_docx(Path(os.environ["REFERENCE_DOCX"]))

    assert len(preview.questions) == 100
    assert [item.code for item in preview.questions] == [f"{index:03d}" for index in range(1, 101)]
    assert sum(item.priority_blind_test for item in preview.questions) == 55
    assert preview.error_count == 0
    assert all(item.image1_prompt and item.image2_prompt for item in preview.questions)
    assert all(item.title == item.answer for item in preview.questions)
    assert preview.questions[0].title == "青之驱魔师"
    assert preview.questions[49].title == "天野阳菜"
    assert preview.questions[-1].title == "圣地巡礼"
