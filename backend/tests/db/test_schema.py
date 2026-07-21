import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import GenerationTask, Question
from app.domain.enums import QuestionState, TaskStatus
from tests.factories import create_project, create_task_context


def test_question_code_is_unique_within_project(session: Session) -> None:
    project = create_project(session)
    session.add_all(
        [
            Question(
                project_id=project.id,
                code="001",
                title="第一题",
                answer="第一题",
                image1_prompt="图1",
                image2_prompt="图2",
                state=QuestionState.IMPORTED,
            ),
            Question(
                project_id=project.id,
                code="001",
                title="重复题",
                answer="重复题",
                image1_prompt="图1",
                image2_prompt="图2",
                state=QuestionState.IMPORTED,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_task_idempotency_key_is_unique(session: Session) -> None:
    run, profile = create_task_context(session)
    task_a = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        idempotency_key="same-key",
        model_id="fake-model",
        request_index=1,
        status=TaskStatus.QUEUED,
    )
    task_b = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        idempotency_key="same-key",
        model_id="fake-model",
        request_index=2,
        status=TaskStatus.QUEUED,
    )
    session.add_all([task_a, task_b])

    with pytest.raises(IntegrityError):
        session.commit()
