from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    QuestionState,
    RunStatus,
    TaskStatus,
)
from app.domain.errors import InvalidStateTransitionError, MissingReferenceImageError
from app.services.prompts import compose_prompt
from app.services.selections import select_image1, select_image2
from app.services.global_settings import get_global_settings


TERMINAL_TASKS = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}
ACTIVE_TASKS = {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.SAVING}


def _profile_for_batch(session: Session, batch: GenerationBatch) -> ProviderProfile:
    profile = session.get(ProviderProfile, batch.provider_profile_id)
    if profile is None:
        raise InvalidStateTransitionError("生图服务配置不存在")
    return profile


def _new_task(
    session: Session,
    run: GenerationRun,
    profile: ProviderProfile,
    request_index: int,
) -> GenerationTask:
    task = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        model_id=profile.model_id,
        request_index=request_index,
        idempotency_key=f"{run.batch_id}:{run.question_id}:{run.stage.value}:{request_index}",
        status=TaskStatus.QUEUED,
    )
    session.add(task)
    session.flush()
    return task


def create_run(
    session: Session,
    batch: GenerationBatch,
    question: Question,
    stage: GenerationStage,
) -> tuple[GenerationRun, GenerationTask]:
    existing = session.scalar(
        select(GenerationRun).where(
            GenerationRun.batch_id == batch.id,
            GenerationRun.question_id == question.id,
            GenerationRun.stage == stage,
        )
    )
    if existing:
        tasks = session.scalars(
            select(GenerationTask)
            .where(GenerationTask.run_id == existing.id)
            .order_by(GenerationTask.request_index)
        ).all()
        if not tasks:
            raise InvalidStateTransitionError("生图运行缺少任务")
        active = next((item for item in reversed(tasks) if item.status in ACTIVE_TASKS), None)
        reference_changed = (
            stage == GenerationStage.IMAGE2
            and question.selected_image1_id
            and existing.reference_asset_id != question.selected_image1_id
        )
        if active and not reference_changed:
            return existing, active
        if reference_changed:
            existing.reference_asset_id = question.selected_image1_id
            existing.status = RunStatus.QUEUED
            task = _new_task(session, existing, _profile_for_batch(session, batch), len(tasks) + 1)
            question.state = QuestionState.IMAGE2_QUEUED
            batch.status = BatchStatus.RUNNING
            session.flush()
            return existing, task
        return existing, tasks[-1]

    profile = _profile_for_batch(session, batch)
    project = session.get(Project, question.project_id)
    if project is None:
        raise InvalidStateTransitionError("项目不存在")
    global_settings = get_global_settings(session)
    if stage == GenerationStage.IMAGE1:
        prompt, requested, semantics = (
            question.image1_prompt,
            batch.q1_requested_outputs,
            batch.q1_output_semantics,
        )
        project_suffix = global_settings.q1_prompt_suffix
        reference_id = None
    else:
        if not question.selected_image1_id:
            raise MissingReferenceImageError("必须先选择第一张图才能生成第二张图")
        reference = session.get(ImageAsset, question.selected_image1_id)
        if not reference or reference.question_id != question.id or reference.stale:
            raise MissingReferenceImageError("当前第一张图无效")
        prompt, requested, semantics = (
            question.image2_prompt,
            batch.q2_requested_outputs,
            batch.q2_output_semantics,
        )
        project_suffix = global_settings.q2_prompt_suffix
        reference_id = reference.id
    suffix = project_suffix
    run = GenerationRun(
        batch_id=batch.id,
        question_id=question.id,
        stage=stage,
        original_prompt=prompt,
        global_suffix=suffix,
        prompt_snapshot=compose_prompt(prompt, suffix),
        requested_outputs=requested,
        output_semantics=semantics,
        reference_asset_id=reference_id,
        status=RunStatus.QUEUED,
    )
    session.add(run)
    session.flush()
    task = _new_task(session, run, profile, 1)
    question.state = (
        QuestionState.IMAGE1_QUEUED
        if stage == GenerationStage.IMAGE1
        else QuestionState.IMAGE2_QUEUED
    )
    session.flush()
    return run, task


def start_batch(session: Session, batch_id: str) -> list[GenerationTask]:
    batch = session.get(GenerationBatch, batch_id)
    if batch is None:
        raise InvalidStateTransitionError("批次不存在")
    questions = session.scalars(
        select(Question)
        .where(
            Question.project_id == batch.project_id,
            Question.code >= batch.start_code,
            Question.code <= batch.end_code,
        )
        .order_by(Question.code)
    ).all()
    tasks = [create_run(session, batch, question, GenerationStage.IMAGE1)[1] for question in questions]
    batch.status = BatchStatus.RUNNING
    session.flush()
    return tasks


def refresh_batch_status(session: Session, batch_id: str) -> BatchStatus:
    batch = session.get(GenerationBatch, batch_id)
    if not batch:
        raise InvalidStateTransitionError("批次不存在")
    questions = session.scalars(
        select(Question).where(
            Question.project_id == batch.project_id,
            Question.code >= batch.start_code,
            Question.code <= batch.end_code,
        )
    ).all()
    runs = session.scalars(
        select(GenerationRun).where(GenerationRun.batch_id == batch.id)
    ).all()
    tasks = session.scalars(
        select(GenerationTask)
        .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
        .where(GenerationRun.batch_id == batch.id)
    ).all()
    if questions and all(question.state == QuestionState.COMPLETED for question in questions):
        batch.status = BatchStatus.COMPLETED
    elif batch.status == BatchStatus.PAUSED:
        pass
    elif any(task.status in ACTIVE_TASKS for task in tasks):
        batch.status = BatchStatus.RUNNING
    elif any(run.status == RunStatus.REVIEW for run in runs):
        batch.status = BatchStatus.WAITING_REVIEW
    else:
        completed = sum(question.state == QuestionState.COMPLETED for question in questions)
        batch.status = BatchStatus.PARTIAL if completed else BatchStatus.FAILED
    session.flush()
    return batch.status


def retry_task(session: Session, task_id: str) -> GenerationTask:
    failed = session.get(GenerationTask, task_id)
    if not failed or failed.status not in {TaskStatus.FAILED, TaskStatus.INTERRUPTED}:
        raise InvalidStateTransitionError("只能重试失败或已中断的任务")
    run = session.get(GenerationRun, failed.run_id)
    if not run:
        raise InvalidStateTransitionError("生图运行不存在")
    tasks = session.scalars(
        select(GenerationTask).where(GenerationTask.run_id == run.id)
    ).all()
    if any(item.status in ACTIVE_TASKS for item in tasks):
        raise InvalidStateTransitionError("该阶段已有任务正在排队或生成")
    batch = session.get(GenerationBatch, run.batch_id)
    question = session.get(Question, run.question_id)
    if not batch or not question:
        raise InvalidStateTransitionError("任务关联数据不完整")
    profile = _profile_for_batch(session, batch)
    retry = _new_task(
        session,
        run,
        profile,
        max(item.request_index for item in tasks) + 1,
    )
    run.status = RunStatus.QUEUED
    question.state = (
        QuestionState.IMAGE1_QUEUED
        if run.stage == GenerationStage.IMAGE1
        else QuestionState.IMAGE2_QUEUED
    )
    batch.status = BatchStatus.RUNNING
    session.flush()
    return retry


def retry_failed_batch_tasks(session: Session, batch_id: str) -> list[GenerationTask]:
    batch = session.get(GenerationBatch, batch_id)
    if not batch:
        raise InvalidStateTransitionError("批次不存在")
    runs = session.scalars(
        select(GenerationRun).where(GenerationRun.batch_id == batch.id)
    ).all()
    retries: list[GenerationTask] = []
    for run in runs:
        latest = session.scalar(
            select(GenerationTask)
            .where(GenerationTask.run_id == run.id)
            .order_by(GenerationTask.request_index.desc())
        )
        if latest and latest.status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED}:
            retries.append(retry_task(session, latest.id))
    if not retries:
        raise InvalidStateTransitionError("当前批次没有可重试的失败任务")
    session.flush()
    return retries


def batch_task_ids(
    session: Session,
    batch_id: str,
    statuses: set[TaskStatus] | None = None,
) -> list[str]:
    statement = (
        select(GenerationTask.id)
        .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
        .where(GenerationRun.batch_id == batch_id)
    )
    if statuses:
        statement = statement.where(GenerationTask.status.in_(statuses))
    return list(session.scalars(statement).all())


def pause_batch(session: Session, batch_id: str) -> list[str]:
    batch = session.get(GenerationBatch, batch_id)
    if not batch:
        raise InvalidStateTransitionError("批次不存在")
    if batch.status != BatchStatus.RUNNING:
        raise InvalidStateTransitionError("只有正在生成的批次可以暂停")
    pending_ids = batch_task_ids(session, batch.id, ACTIVE_TASKS)
    batch.status = BatchStatus.PAUSED
    session.flush()
    return pending_ids


def resume_batch(session: Session, batch_id: str) -> tuple[list[str], list[str]]:
    batch = session.get(GenerationBatch, batch_id)
    if not batch:
        raise InvalidStateTransitionError("批次不存在")
    if batch.status != BatchStatus.PAUSED:
        raise InvalidStateTransitionError("只有已暂停的批次可以继续")
    held_ids = batch_task_ids(session, batch.id)
    interrupted = session.scalars(
        select(GenerationTask)
        .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
        .where(
            GenerationRun.batch_id == batch.id,
            GenerationTask.status == TaskStatus.INTERRUPTED,
        )
    ).all()
    for task in interrupted:
        retry_task(session, task.id)
    batch.status = BatchStatus.RUNNING
    queued_ids = batch_task_ids(session, batch.id, {TaskStatus.QUEUED})
    refresh_batch_status(session, batch.id)
    session.flush()
    return queued_ids, held_ids


def finalize_task(session: Session, task_id: str) -> GenerationRun:
    task = session.get(GenerationTask, task_id)
    if task is None:
        raise InvalidStateTransitionError("任务不存在")
    run = session.get(GenerationRun, task.run_id)
    if run is None:
        raise InvalidStateTransitionError("生图运行不存在")
    tasks = session.scalars(select(GenerationTask).where(GenerationTask.run_id == run.id)).all()
    if any(item.status not in TERMINAL_TASKS for item in tasks):
        return run
    assets = session.scalars(
        select(ImageAsset)
        .join(GenerationTask, ImageAsset.task_id == GenerationTask.id)
        .where(GenerationTask.run_id == run.id, ImageAsset.stale.is_(False))
        .order_by(ImageAsset.output_index)
    ).all()
    question = session.get(Question, run.question_id)
    batch = session.get(GenerationBatch, run.batch_id)
    if question is None or batch is None:
        raise InvalidStateTransitionError("任务关联数据不完整")
    was_paused = batch.status == BatchStatus.PAUSED
    if not assets:
        run.status = RunStatus.FAILED
        question.state = QuestionState.FAILED
    elif len(assets) == 1:
        run.status = RunStatus.COMPLETED
        if run.stage == GenerationStage.IMAGE1:
            select_image1(session, question.id, assets[0].id)
            if batch.auto_continue:
                create_run(session, batch, question, GenerationStage.IMAGE2)
        else:
            select_image2(session, question.id, assets[0].id)
    else:
        run.status = RunStatus.REVIEW
        question.state = (
            QuestionState.IMAGE1_REVIEW
            if run.stage == GenerationStage.IMAGE1
            else QuestionState.IMAGE2_REVIEW
        )
        batch.status = BatchStatus.WAITING_REVIEW
    if was_paused:
        batch.status = BatchStatus.PAUSED
    refresh_batch_status(session, batch.id)
    session.flush()
    return run


def mark_task_succeeded(
    session: Session, task: GenerationTask, actual_count: int
) -> GenerationRun:
    task.status = TaskStatus.SUCCEEDED
    task.actual_output_count = actual_count
    task.finished_at = datetime.now(UTC)
    session.flush()
    return finalize_task(session, task.id)


def remaining_questions(session: Session, batch_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(GenerationRun)
            .where(GenerationRun.batch_id == batch_id, GenerationRun.status != RunStatus.COMPLETED)
        )
        or 0
    )
