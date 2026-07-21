from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import GenerationBatch, GenerationRun, GenerationTask, Question
from app.domain.enums import BatchStatus, QuestionState, RunStatus, TaskStatus
from app.queue.recovery import recover_interrupted_tasks
from tests.factories import create_task_context


def _task(session: Session, status: TaskStatus) -> tuple[GenerationTask, GenerationRun]:
    run, profile = create_task_context(session)
    task = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        idempotency_key=f"recovery-{status.value}",
        model_id="fake-model",
        request_index=1,
        status=status,
    )
    session.add(task)
    session.flush()
    return task, run


def test_recovery_preserves_delayed_queue(session: Session) -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)
    task, _run = _task(session, TaskStatus.QUEUED)
    task.retry_not_before = now + timedelta(seconds=75)
    session.commit()

    queued, interrupted = recover_interrupted_tasks(session, now=now)

    assert interrupted == []
    assert queued == [(task.id, 75.0)]


def test_recovery_pauses_uncertain_inflight_batch(session: Session) -> None:
    task, run = _task(session, TaskStatus.RUNNING)
    run.status = RunStatus.RUNNING
    question = session.get(Question, run.question_id)
    batch = session.get(GenerationBatch, run.batch_id)
    question.state = QuestionState.IMAGE1_RUNNING
    batch.status = BatchStatus.RUNNING
    session.commit()

    queued, interrupted = recover_interrupted_tasks(session)

    assert queued == []
    assert interrupted == [task.id]
    assert task.status == TaskStatus.INTERRUPTED
    assert run.status == RunStatus.INTERRUPTED
    assert question.state == QuestionState.INTERRUPTED
    assert batch.status == BatchStatus.PAUSED
