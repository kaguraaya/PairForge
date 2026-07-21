import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ImageAsset
from app.domain.enums import GenerationStage, TaskStatus
from app.db.models import GenerationTask
from tests.factories import create_task_context


def test_sqlite_foreign_keys_are_enabled(session: Session) -> None:
    assert session.scalar(text("PRAGMA foreign_keys")) == 1


def test_asset_cannot_reference_missing_question(session: Session) -> None:
    run, profile = create_task_context(session)
    task = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        idempotency_key="asset-test",
        model_id="fake",
        request_index=1,
        status=TaskStatus.SUCCEEDED,
    )
    session.add(task)
    session.flush()
    session.add(
        ImageAsset(
            task_id=task.id,
            question_id="missing-question",
            stage=GenerationStage.IMAGE1,
            output_index=1,
            local_path="missing.png",
            sha256="0" * 64,
            width=1,
            height=1,
            mime_type="image/png",
            prompt_snapshot="prompt",
            provider="fake",
            model="fake",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
