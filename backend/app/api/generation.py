from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import (
    GenerationBatch,
    GenerationRun,
    GenerationTask,
    ImageAsset,
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
from app.domain.errors import DomainError
from app.providers.base import ModelCapabilities
from app.providers.registry import model_registry
from app.services.generation import (
    create_run,
    pause_batch,
    refresh_batch_status,
    resume_batch,
    retry_failed_batch_tasks,
    retry_task,
    start_batch,
)
from app.services.credentials import available_credentials
from app.services.quota import estimate_range
from app.services.quota_status import preflight_profile
from app.services.selections import select_image1, select_image2

router = APIRouter(prefix="/api/generation", tags=["generation"])


class RangeRequest(BaseModel):
    project_id: str
    provider_profile_id: str
    start_code: str
    end_code: str
    q1_outputs: int = Field(default=1, ge=1)
    q2_outputs: int = Field(default=1, ge=1)
    parallelism: int = Field(default=8, ge=1, le=12)
    auto_continue: bool = True


class SelectRequest(BaseModel):
    question_id: str
    asset_id: str
    stage: GenerationStage


def capabilities_for(profile: ProviderProfile) -> ModelCapabilities:
    try:
        return model_registry.get(profile.provider, profile.model_id)
    except KeyError:
        config = profile.config or {}
        maximum = int(config.get("max_outputs", 4))
        return ModelCapabilities(
            provider=profile.provider,
            model=profile.model_id,
            display_name=profile.display_name,
            supports_text_to_image=True,
            supports_image_edit=bool(config.get("supports_image_edit", True)),
            min_outputs=1,
            max_text_outputs=maximum,
            max_edit_outputs=maximum,
            default_size=str(config.get("default_size", "1024x1024")),
            single_output_semantics=OutputSemantics.FIXED,
            multiple_output_semantics=OutputSemantics.EXACT,
            unit_price_cny=Decimal(str(config.get("unit_price_cny", 0))),
            price_checked_on=str(config.get("price_checked_on", "用户自定义")),
            documentation_url=str(config.get("documentation_url", "")),
        )


def get_estimate(body: RangeRequest, session: Session):
    profile = session.get(ProviderProfile, body.provider_profile_id)
    if not profile or profile.project_id != body.project_id:
        raise HTTPException(404, "生图服务配置不存在或不属于当前项目")
    capabilities = capabilities_for(profile)
    try:
        estimate = estimate_range(
            session,
            body.project_id,
            body.start_code,
            body.end_code,
            body.q1_outputs,
            body.q2_outputs,
            capabilities,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if estimate.question_count == 0:
        raise HTTPException(400, "所选编号范围内没有题目")
    return profile, capabilities, estimate


@router.post("/estimate")
def estimate(body: RangeRequest, session: Session = Depends(get_session)) -> dict[str, object]:
    _profile, capabilities, result = get_estimate(body, session)
    return {
        "question_count": result.question_count,
        "image1_maximum": result.image1_maximum,
        "image2_maximum": result.image2_maximum,
        "total_maximum": result.total_maximum,
        "estimated_cost_cny": str(result.estimated_cost_cny),
        "actual_may_be_lower": result.actual_may_be_lower,
        "price_checked_on": capabilities.price_checked_on,
        "unit_price_cny": str(capabilities.unit_price_cny),
    }


@router.post("/start")
async def start(
    body: RangeRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    profile, capabilities, estimate = get_estimate(body, session)
    usable_credentials = [
        credential
        for credential in available_credentials(session, profile.id)
        if request.app.state.secret_store.get(credential.id)
    ]
    if not usable_credentials:
        raise HTTPException(409, "没有可用 API Key，请先在设置中添加或恢复密钥")
    batch = GenerationBatch(
        project_id=body.project_id,
        provider_profile_id=profile.id,
        start_code=body.start_code,
        end_code=body.end_code,
        question_count=estimate.question_count,
        q1_requested_outputs=body.q1_outputs,
        q2_requested_outputs=body.q2_outputs,
        q1_output_semantics=(
            capabilities.single_output_semantics
            if body.q1_outputs == 1
            else capabilities.multiple_output_semantics
        ),
        q2_output_semantics=(
            capabilities.single_output_semantics
            if body.q2_outputs == 1
            else capabilities.multiple_output_semantics
        ),
        image1_maximum=estimate.image1_maximum,
        image2_maximum=estimate.image2_maximum,
        total_maximum=estimate.total_maximum,
        unit_price_cny=float(capabilities.unit_price_cny),
        estimated_cost_cny=float(estimate.estimated_cost_cny),
        price_checked_at=datetime.now().astimezone(),
        auto_continue=body.auto_continue,
        status=BatchStatus.CONFIRMED,
    )
    session.add(batch)
    session.flush()
    tasks = start_batch(session, batch.id)
    task_ids = [task.id for task in tasks]
    session.commit()
    applied_parallelism = request.app.state.scheduler.set_concurrency(body.parallelism)
    for task_id in task_ids:
        await request.app.state.scheduler.submit(task_id)
    return {
        "batch_id": batch.id,
        "queued_tasks": len(task_ids),
        "parallelism": applied_parallelism,
    }


@router.post("/preflight/{profile_id}")
async def preflight(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    profile = session.get(ProviderProfile, profile_id)
    if not profile:
        raise HTTPException(404, "生图服务配置不存在")
    result = await preflight_profile(
        session, request.app.state.secret_store, profile
    )
    session.commit()
    return result


@router.post("/select")
async def select_candidate(
    body: SelectRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        asset = session.get(ImageAsset, body.asset_id)
        source_task = session.get(GenerationTask, asset.task_id) if asset else None
        source_run = session.get(GenerationRun, source_task.run_id) if source_task else None
        batch = session.get(GenerationBatch, source_run.batch_id) if source_run else None
        if batch is None:
            raise HTTPException(409, "找不到该图片所属批次")
        if body.stage == GenerationStage.IMAGE2:
            question = select_image2(session, body.question_id, body.asset_id)
            refresh_batch_status(session, batch.id)
            task_id = None
        else:
            question = select_image1(session, body.question_id, body.asset_id)
            _run, second_task = create_run(session, batch, question, GenerationStage.IMAGE2)
            task_id = second_task.id
        session.commit()
    except DomainError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    if task_id:
        await request.app.state.scheduler.submit(task_id)
    return {"question_id": question.id, "state": question.state, "queued_task_id": task_id}


@router.post("/tasks/{task_id}/retry")
async def retry_failed_task(
    task_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        task = retry_task(session, task_id)
        session.commit()
    except DomainError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    await request.app.state.scheduler.submit(task.id)
    return {"task_id": task.id, "status": task.status}


@router.post("/batches/{batch_id}/retry-failed")
async def retry_failed_batch(
    batch_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        tasks = retry_failed_batch_tasks(session, batch_id)
        task_ids = [task.id for task in tasks]
        session.commit()
    except DomainError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    for task_id in task_ids:
        await request.app.state.scheduler.submit(task_id)
    return {"retried_count": len(task_ids), "task_ids": task_ids}


def batch_payload(
    batch: GenerationBatch,
    session: Session,
    scheduler,
) -> dict[str, object]:
    questions = session.scalars(
        select(Question).where(
            Question.project_id == batch.project_id,
            Question.code >= batch.start_code,
            Question.code <= batch.end_code,
        )
    ).all()
    runs = session.scalars(select(GenerationRun).where(GenerationRun.batch_id == batch.id)).all()
    tasks = session.scalars(
        select(GenerationTask)
        .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
        .where(GenerationRun.batch_id == batch.id)
    ).all()
    completed_stages = sum(
        run.status in {RunStatus.COMPLETED, RunStatus.REVIEW} for run in runs
    )
    expected_stages = batch.question_count * 2
    review_questions = sum(
        question.state in {QuestionState.IMAGE1_REVIEW, QuestionState.IMAGE2_REVIEW}
        for question in questions
    )
    failed_questions = sum(
        question.state in {QuestionState.FAILED, QuestionState.INTERRUPTED}
        for question in questions
    )
    now = datetime.now(UTC)
    retrying_tasks = [
        task
        for task in tasks
        if task.status == TaskStatus.QUEUED
        and task.error_category == "rate_limit"
        and task.retry_not_before is not None
    ]
    retry_times = [
        (
            task.retry_not_before.replace(tzinfo=UTC)
            if task.retry_not_before and task.retry_not_before.tzinfo is None
            else task.retry_not_before
        )
        for task in retrying_tasks
    ]
    future_retry_times = [value for value in retry_times if value and value > now]
    return {
        "id": batch.id,
        "status": batch.status,
        "start_code": batch.start_code,
        "end_code": batch.end_code,
        "question_count": batch.question_count,
        "completed_question_count": sum(
            question.state == QuestionState.COMPLETED for question in questions
        ),
        "review_question_count": review_questions,
        "failed_question_count": failed_questions,
        "completed_stage_count": completed_stages,
        "expected_stage_count": expected_stages,
        "progress_percent": round(completed_stages * 100 / expected_stages) if expected_stages else 0,
        "running_task_count": sum(
            task.status in {TaskStatus.RUNNING, TaskStatus.SAVING} for task in tasks
        ),
        "queued_task_count": sum(task.status == TaskStatus.QUEUED for task in tasks),
        "retry_waiting_count": len(future_retry_times),
        "next_retry_at": min(future_retry_times).isoformat() if future_retry_times else None,
        "interrupted_task_count": sum(
            task.status == TaskStatus.INTERRUPTED for task in tasks
        ),
        "can_pause": batch.status == BatchStatus.RUNNING,
        "can_resume": batch.status == BatchStatus.PAUSED,
        "scheduler_parallelism": scheduler.concurrency,
        "scheduler_active_count": scheduler.active_count,
        "scheduler_queued_count": scheduler.queued_count,
        "scheduler_delayed_count": scheduler.delayed_count,
        "scheduler_held_count": scheduler.held_count,
        "runs": [
            {
                "id": run.id,
                "question_id": run.question_id,
                "stage": run.stage,
                "status": run.status,
                "requested_outputs": run.requested_outputs,
            }
            for run in runs
        ],
    }


@router.post("/batches/{batch_id}/pause")
async def pause_generation_batch(
    batch_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        pending_ids = pause_batch(session, batch_id)
        request.app.state.scheduler.hold(pending_ids)
        session.commit()
    except DomainError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    batch = session.get(GenerationBatch, batch_id)
    return batch_payload(batch, session, request.app.state.scheduler)


@router.post("/batches/{batch_id}/resume")
async def resume_generation_batch(
    batch_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        queued_ids, held_ids = resume_batch(session, batch_id)
        queued_tasks = {
            task.id: task
            for task in session.scalars(
                select(GenerationTask).where(GenerationTask.id.in_(queued_ids))
            ).all()
        }
        session.commit()
    except DomainError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    request.app.state.scheduler.release(held_ids)
    now = datetime.now(UTC)
    for task_id in queued_ids:
        retry_at = queued_tasks[task_id].retry_not_before
        if retry_at is not None and retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = max(0.0, (retry_at - now).total_seconds()) if retry_at else 0.0
        await request.app.state.scheduler.submit(task_id, delay)
    batch = session.get(GenerationBatch, batch_id)
    return batch_payload(batch, session, request.app.state.scheduler)


@router.get("/projects/{project_id}/latest-batch")
def latest_batch_status(
    project_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object] | None:
    batch = session.scalar(
        select(GenerationBatch)
        .where(GenerationBatch.project_id == project_id)
        .order_by(GenerationBatch.created_at.desc())
    )
    if not batch:
        return None
    return batch_payload(batch, session, request.app.state.scheduler)


@router.get("/batches/{batch_id}")
def batch_status(
    batch_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    batch = session.get(GenerationBatch, batch_id)
    if not batch:
        raise HTTPException(404, "批次不存在")
    return batch_payload(batch, session, request.app.state.scheduler)
