from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re

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


def is_pending_export(question: Question) -> bool:
    return bool(
        question.selected_image1_id
        and question.selected_image2_id
        and (
            question.selected_image1_id != question.last_exported_image1_id
            or question.selected_image2_id != question.last_exported_image2_id
        )
    )


def _create_batch_directory(exports_root: Path, now: datetime) -> Path:
    exports_root.mkdir(parents=True, exist_ok=True)
    date_prefix = now.strftime("%Y%m%d")
    pattern = re.compile(rf"^{date_prefix}-(\d{{2,}})$")
    used_numbers = {
        int(match.group(1))
        for path in exports_root.iterdir()
        if path.is_dir() and (match := pattern.fullmatch(path.name))
    }
    sequence = max(used_numbers, default=0) + 1
    while True:
        directory = exports_root / f"{date_prefix}-{sequence:02d}"
        try:
            directory.mkdir(parents=False, exist_ok=False)
            return directory
        except FileExistsError:
            sequence += 1


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
    pending = [question for question in questions if is_pending_export(question)]
    if not pending:
        raise ExportValidationError("没有新增或变更的完整题目可导出")
    pairs = [(question, *_selected_pair(session, question)) for question in pending]

    directory = _create_batch_directory(exports_root, datetime.now())
    images_directory = directory
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
        question.last_exported_image1_id = image1.id
        question.last_exported_image2_id = image2.id

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
    session.flush()
    return ExportResult(directory, images_directory, len(pairs), len(pairs) * 2)
