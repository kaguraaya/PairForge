from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationBatch, GenerationRun, GenerationTask, Question
from app.domain.enums import BatchStatus, QuestionState, RunStatus, TaskStatus


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def recover_interrupted_tasks(
    session: Session, *, now: datetime | None = None
) -> tuple[list[tuple[str, float]], list[str]]:
    checked_at = now or datetime.now(UTC)
    running = session.scalars(
        select(GenerationTask).where(
            GenerationTask.status.in_([TaskStatus.RUNNING, TaskStatus.SAVING])
        )
    ).all()
    interrupted_ids: list[str] = []
    for task in running:
        run = session.get(GenerationRun, task.run_id)
        question = session.get(Question, run.question_id) if run else None
        batch = session.get(GenerationBatch, run.batch_id) if run else None
        task.status = TaskStatus.INTERRUPTED
        task.finished_at = checked_at
        task.error_category = "interrupted"
        task.error_message_safe = "软件上次退出时请求仍在进行；为避免重复扣费，已暂停并等待继续"
        if run:
            run.status = RunStatus.INTERRUPTED
        if question:
            question.state = QuestionState.INTERRUPTED
        if batch:
            batch.status = BatchStatus.PAUSED
        interrupted_ids.append(task.id)

    queued = session.scalars(
        select(GenerationTask)
        .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
        .join(GenerationBatch, GenerationRun.batch_id == GenerationBatch.id)
        .where(
            GenerationTask.status == TaskStatus.QUEUED,
            GenerationBatch.status != BatchStatus.PAUSED,
        )
    ).all()
    recovered: list[tuple[str, float]] = []
    for task in queued:
        retry_at = _aware(task.retry_not_before)
        delay = max(0.0, (retry_at - checked_at).total_seconds()) if retry_at else 0.0
        recovered.append((task.id, delay))
    session.flush()
    return recovered, interrupted_ids
