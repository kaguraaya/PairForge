from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImageAsset, Question
from app.domain.enums import GenerationStage
from app.storage.names import final_name


class ExportValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExportResult:
    directory: Path
    images_directory: Path
    question_count: int
    image_count: int


def _selected_pair(session: Session, question: Question) -> tuple[ImageAsset, ImageAsset]:
    image1 = session.get(ImageAsset, question.selected_image1_id)
    image2 = session.get(ImageAsset, question.selected_image2_id)
    if not image1 or not image2:
        raise ExportValidationError(f"题目 {question.code} 尚未选定两张图片")
    if image1.question_id != question.id or image2.question_id != question.id:
        raise ExportValidationError(f"题目 {question.code} 的图片关联异常")
    if image1.stage is not GenerationStage.IMAGE1 or image2.stage is not GenerationStage.IMAGE2:
        raise ExportValidationError(f"题目 {question.code} 的图片阶段异常")
    if image2.stale or image2.reference_asset_id != image1.id:
        raise ExportValidationError(f"题目 {question.code} 的第二张图引用已失效")
    if not Path(image1.local_path).is_file() or not Path(image2.local_path).is_file():
        raise ExportValidationError(f"题目 {question.code} 的图片文件缺失")
    return image1, image2


def export_project(session: Session, project_id: str, exports_root: Path) -> ExportResult:
    questions = session.scalars(
        select(Question).where(Question.project_id == project_id).order_by(Question.code)
    ).all()
    completed = [q for q in questions if q.selected_image1_id and q.selected_image2_id]
    if not completed:
        raise ExportValidationError("没有可导出的完整题目")
    pairs = [(question, *_selected_pair(session, question)) for question in completed]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    directory = exports_root / stamp
    images_directory = directory / "final_images"
    images_directory.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, object]] = []

    for question, image1, image2 in pairs:
        filenames = []
        for stage_number, asset in enumerate((image1, image2), start=1):
            extension = Path(asset.local_path).suffix or ".png"
            filename = final_name(question.code, question.answer, stage_number, extension)
            shutil.copy2(asset.local_path, images_directory / filename)
            filenames.append(filename)
        manifest.append(
            {
                "question_id": question.id,
                "code": question.code,
                "answer": question.answer,
                "image1": filenames[0],
                "image2": filenames[1],
                "image1_asset_id": image1.id,
                "image2_asset_id": image2.id,
                "image2_reference_asset_id": image2.reference_asset_id,
                "image1_prompt": image1.prompt_snapshot,
                "image2_prompt": image2.prompt_snapshot,
                "provider": image1.provider,
                "image1_model": image1.model,
                "image2_model": image2.model,
            }
        )

    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (directory / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
    summary = asdict(
        ExportResult(
            directory=directory,
            images_directory=images_directory,
            question_count=len(pairs),
            image_count=len(pairs) * 2,
        )
    )
    (directory / "export_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return ExportResult(directory, images_directory, len(pairs), len(pairs) * 2)

