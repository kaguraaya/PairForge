from io import BytesIO

import pytest
from PIL import Image

from app.domain.enums import GenerationStage
from app.storage.images import InvalidImageError, store_image_atomic
from app.storage.layout import WorkspaceLayout
from app.storage.names import candidate_name, final_name


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), "#7357ff").save(output, format="PNG")
    return output.getvalue()


def test_clean_flat_names_are_traceable() -> None:
    assert final_name("001", "青之驱魔师", 1) == "001__青之驱魔师__01.png"
    assert ":" not in final_name("002", "A:B", 2)
    name = candidate_name("001", GenerationStage.IMAGE1, 3, 2, "12345678-abcd")
    assert name == "001__Q1__REQ03__OUT02__12345678.png"


def test_layout_separates_stages_without_question_folders(tmp_path) -> None:
    layout = WorkspaceLayout(tmp_path / "中文工作区")
    layout.ensure()
    assert layout.candidate_dir(GenerationStage.IMAGE1).name == "q1_candidates"
    assert layout.candidate_dir(GenerationStage.IMAGE2).name == "q2_candidates"


def test_atomic_storage_validates_and_hashes(tmp_path) -> None:
    stored = store_image_atomic(png_bytes(), tmp_path / "图像.png")
    assert stored.path.exists()
    assert stored.width == 32 and stored.height == 24
    assert len(stored.sha256) == 64
    with pytest.raises(InvalidImageError):
        store_image_atomic(b"not an image", tmp_path / "bad.png")

