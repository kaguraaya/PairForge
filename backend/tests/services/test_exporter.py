import hashlib
import json
import re

import pytest

from app.db.models import (
    GenerationBatch,
    GenerationRun,
    GenerationTask,
    ImageAsset,
    Project,
    ProviderProfile,
    Question,
)
from app.domain.enums import (
    BatchStatus,
    GenerationStage,
    OutputSemantics,
    QuestionState,
    RunStatus,
    TaskStatus,
)
from app.services.exporter import ExportValidationError, export_project


def completed_pair(session, tmp_path, project, profile, code: str) -> Question:
    question = Question(
        project_id=project.id,
        code=code,
        title=f"题目 {code}",
        answer=f"答案{code}",
        image1_prompt="图一",
        image2_prompt="图二",
        state=QuestionState.COMPLETED,
    )
    session.add(question)
    session.flush()
    batch = GenerationBatch(
        project_id=project.id,
        provider_profile_id=profile.id,
        start_code=code,
        end_code=code,
        question_count=1,
        q1_requested_outputs=1,
        q2_requested_outputs=1,
        q1_output_semantics=OutputSemantics.FIXED,
        q2_output_semantics=OutputSemantics.FIXED,
        image1_maximum=1,
        image2_maximum=1,
        total_maximum=2,
        status=BatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    assets = []
    for index, stage in enumerate((GenerationStage.IMAGE1, GenerationStage.IMAGE2), start=1):
        run = GenerationRun(
            batch_id=batch.id,
            question_id=question.id,
            stage=stage,
            original_prompt=stage.value,
            prompt_snapshot=stage.value,
            requested_outputs=1,
            output_semantics=OutputSemantics.FIXED,
            reference_asset_id=assets[0].id if assets else None,
            status=RunStatus.COMPLETED,
        )
        session.add(run)
        session.flush()
        task = GenerationTask(
            run_id=run.id,
            provider_profile_id=profile.id,
            model_id="fake-model",
            request_index=1,
            idempotency_key=f"{question.id}:{stage.value}",
            status=TaskStatus.SUCCEEDED,
            actual_output_count=1,
        )
        session.add(task)
        session.flush()
        image_path = tmp_path / f"{code}-{index}.png"
        image_path.write_bytes(f"image-{code}-{index}".encode())
        asset = ImageAsset(
            task_id=task.id,
            question_id=question.id,
            stage=stage,
            output_index=1,
            local_path=str(image_path),
            sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
            width=4,
            height=3,
            mime_type="image/png",
            file_size=image_path.stat().st_size,
            reference_asset_id=assets[0].id if assets else None,
            selected=True,
            prompt_snapshot=stage.value,
            provider="fake",
            model="fake-model",
        )
        session.add(asset)
        session.flush()
        assets.append(asset)
    question.selected_image1_id = assets[0].id
    question.selected_image2_id = assets[1].id
    session.flush()
    return question


def test_export_only_writes_new_or_changed_pairs_to_short_batch_folder(session, tmp_path) -> None:
    project = Project(name="导出测试", workspace_path=str(tmp_path))
    session.add(project)
    session.flush()
    profile = ProviderProfile(
        project_id=project.id,
        provider="fake",
        display_name="Fake",
        base_url="https://example.invalid",
        model_id="fake-model",
    )
    session.add(profile)
    session.flush()
    first = completed_pair(session, tmp_path, project, profile, "001")
    added = completed_pair(session, tmp_path, project, profile, "026")
    exports_root = tmp_path / "exports"
    legacy_directory = exports_root / "20260721_120000_000000"
    legacy_directory.mkdir(parents=True)
    (legacy_directory / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "question_id": first.id,
                    "image1_asset_id": first.selected_image1_id,
                    "image2_asset_id": first.selected_image2_id,
                }
            ]
        ),
        encoding="utf-8",
    )

    initial = export_project(session, project.id, exports_root)

    assert re.fullmatch(r"\d{8}-01", initial.directory.name)
    assert initial.images_directory == initial.directory
    assert initial.question_count == 1
    assert len(list(initial.directory.glob("*.png"))) == 2
    assert {path.name for path in initial.directory.glob("*.png")} == {
        "026__答案026__01.png",
        "026__答案026__02.png",
    }
    assert not (initial.directory / "final_images").exists()
    assert first.last_exported_image1_id == first.selected_image1_id
    assert first.last_exported_image2_id == first.selected_image2_id
    assert added.last_exported_image1_id == added.selected_image1_id
    assert added.last_exported_image2_id == added.selected_image2_id

    with pytest.raises(ExportValidationError, match="没有新增或变更"):
        export_project(session, project.id, exports_root)

    first.last_exported_image2_id = "previous-selection"
    incremental = export_project(session, project.id, exports_root)

    assert incremental.directory.name.endswith("-02")
    assert incremental.question_count == 1
    assert {path.name for path in incremental.directory.glob("*.png")} == {
        "001__答案001__01.png",
        "001__答案001__02.png",
    }
