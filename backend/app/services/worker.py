from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    GenerationBatch,
    GenerationRun,
    GenerationTask,
    ImageAsset,
    Project,
    ProviderCredential,
    ProviderProfile,
    Question,
    new_id,
)
from app.domain.enums import BatchStatus, GenerationStage, QuestionState, RunStatus, TaskStatus
from app.providers.alibaba import AlibabaProvider
from app.providers.base import GenerationRequest, ProviderConfig
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import model_registry
from app.providers.size_rules import normalize_image_size
from app.providers.volcengine import VolcengineProvider
from app.queue.scheduler import RetryTask
from app.services.credentials import (
    acquire_credential,
    record_credential_failure,
    record_credential_success,
)
from app.services.generation import finalize_task, mark_task_succeeded
from app.storage.images import InvalidImageError, store_image_atomic
from app.storage.layout import WorkspaceLayout
from app.storage.names import candidate_name


def image_data_uri(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def source_bytes(source) -> bytes:
    if source.b64_json:
        try:
            return base64.b64decode(source.b64_json, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidImageError("服务返回了无效的 Base64 图片") from error
    if not source.url:
        raise InvalidImageError("服务没有返回图片地址")
    parsed = urlparse(source.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InvalidImageError("服务返回了不安全的图片地址")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as error:
        raise InvalidImageError("无法验证服务返回的图片地址") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise InvalidImageError("服务返回的图片地址指向本地或私有网络")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
        response = await client.get(source.url)
        response.raise_for_status()
        data = response.content
    if len(data) > 50 * 1024 * 1024:
        raise InvalidImageError("单张图片超过 50MB")
    return data


def provider_for(profile: ProviderProfile, api_key: str):
    config = ProviderConfig(api_key, profile.base_url, profile.workspace_id)
    if profile.provider == "volcengine":
        return VolcengineProvider(config)
    if profile.provider == "alibaba":
        return AlibabaProvider(config)
    return OpenAICompatibleProvider(config)


def rate_limit_delay(attempt: int, retry_after_seconds: float | None) -> float:
    if retry_after_seconds is not None:
        return max(1.0, min(float(retry_after_seconds), 3600.0))
    return float(min(60 * (2 ** max(0, attempt - 1)), 900))


async def execute_task(app, task_id: str) -> None:
    with Session(app.state.engine, expire_on_commit=False) as session:
        task = session.get(GenerationTask, task_id)
        if not task or task.status != TaskStatus.QUEUED:
            return
        run = session.get(GenerationRun, task.run_id)
        profile = session.get(ProviderProfile, task.provider_profile_id)
        question = session.get(Question, run.question_id) if run else None
        if not run or not profile or not question:
            task.status = TaskStatus.FAILED
            task.error_category = "invalid_state"
            task.error_message_safe = "任务关联数据不完整"
            session.commit()
            return
        batch = session.get(GenerationBatch, run.batch_id)
        if batch and batch.status == BatchStatus.PAUSED:
            # The scheduler may have claimed this queued task just before the
            # pause transaction committed. Keep it scheduler-owned so a fast
            # pause -> resume cannot strand the still-persisted queued task.
            raise RetryTask(0)
        acquired = acquire_credential(session, app.state.secret_store, profile)
        if not acquired:
            task.status = TaskStatus.FAILED
            task.error_category = "authentication"
            task.error_message_safe = "没有可用的 API 密钥，请检查密钥状态或额度"
            task.finished_at = datetime.now(UTC)
            session.flush()
            finalize_task(session, task.id)
            session.commit()
            return
        credential, api_key = acquired
        credential_id = credential.id
        reference = session.get(ImageAsset, run.reference_asset_id) if run.reference_asset_id else None
        reference_data = None
        if run.stage == GenerationStage.IMAGE2:
            if (
                not reference
                or reference.question_id != question.id
                or question.selected_image1_id != reference.id
                or reference.stale
            ):
                task.status = TaskStatus.FAILED
                task.error_category = "stale_reference"
                task.error_message_safe = "第一张图已经变化，第二张图任务已停止"
                session.flush()
                finalize_task(session, task.id)
                session.commit()
                return
            reference_data = image_data_uri(Path(reference.local_path), reference.mime_type)
        profile_config = profile.config or {}
        try:
            caps = model_registry.get(profile.provider, profile.model_id)
            size = str(profile_config.get("size") or caps.default_size)
        except KeyError:
            size = str(
                profile_config.get("size")
                or profile_config.get("default_size", "1024x1024")
            )
        size = normalize_image_size(profile.provider, profile.model_id, size)
        provider_factory = getattr(app.state, "provider_factory", provider_for)
        provider = provider_factory(profile, api_key)
        provider_request = GenerationRequest(
            model=task.model_id,
            prompt=run.prompt_snapshot,
            stage=run.stage,
            requested_outputs=run.requested_outputs,
            size=size,
            reference_image=reference_data,
            watermark=bool(profile_config.get("watermark", False)),
            seed=(
                int(profile_config["seed"])
                if profile_config.get("seed") is not None
                else None
            ),
            guidance_scale=(
                float(profile_config["guidance_scale"])
                if profile_config.get("guidance_scale") is not None
                else None
            ),
            prompt_extend=(
                bool(profile_config["prompt_extend"])
                if "prompt_extend" in profile_config
                else None
            ),
            thinking_mode=(
                bool(profile_config["thinking_mode"])
                if "thinking_mode" in profile_config
                else None
            ),
        )
        task.status = TaskStatus.RUNNING
        task.retry_not_before = None
        task.started_at = datetime.now(UTC)
        run.status = RunStatus.RUNNING
        question.state = (
            QuestionState.IMAGE1_RUNNING
            if run.stage == GenerationStage.IMAGE1
            else QuestionState.IMAGE2_RUNNING
        )
        if batch:
            batch.status = BatchStatus.RUNNING
        session.commit()

    try:
        while True:
            try:
                result = await provider.generate(provider_request)
                break
            except ProviderError as provider_error:
                with Session(app.state.engine, expire_on_commit=False) as session:
                    retry_task = session.get(GenerationTask, task_id)
                    failed_credential = session.get(ProviderCredential, credential_id)
                    profile_for_retry = session.get(ProviderProfile, task.provider_profile_id)
                    delay_seconds = rate_limit_delay(
                        retry_task.attempt if retry_task else 1,
                        provider_error.retry_after_seconds,
                    )
                    if failed_credential:
                        record_credential_failure(
                            session,
                            failed_credential,
                            provider_error.category,
                            provider_error.safe_message,
                            cooldown_seconds=(
                                delay_seconds
                                if provider_error.category == ProviderErrorCategory.RATE_LIMIT
                                else None
                            ),
                        )
                    retryable_with_another_key = provider_error.category in {
                        ProviderErrorCategory.AUTHENTICATION,
                        ProviderErrorCategory.QUOTA,
                        ProviderErrorCategory.RATE_LIMIT,
                    }
                    replacement = (
                        acquire_credential(
                            session, app.state.secret_store, profile_for_retry
                        )
                        if retryable_with_another_key and profile_for_retry
                        else None
                    )
                    if (
                        not replacement
                        and retry_task
                        and provider_error.category == ProviderErrorCategory.RATE_LIMIT
                    ):
                        retry_run = session.get(GenerationRun, retry_task.run_id)
                        retry_question = (
                            session.get(Question, retry_run.question_id) if retry_run else None
                        )
                        retry_batch = (
                            session.get(GenerationBatch, retry_run.batch_id) if retry_run else None
                        )
                        retry_task.status = TaskStatus.QUEUED
                        retry_task.attempt += 1
                        retry_task.retry_not_before = datetime.now(UTC) + timedelta(
                            seconds=delay_seconds
                        )
                        retry_task.started_at = None
                        retry_task.finished_at = None
                        retry_task.error_category = ProviderErrorCategory.RATE_LIMIT.value
                        retry_task.error_message_safe = (
                            f"触发厂商限流，将在约 {int(delay_seconds)} 秒后自动继续"
                        )
                        if retry_run:
                            retry_run.status = RunStatus.QUEUED
                        if retry_question and retry_run:
                            retry_question.state = (
                                QuestionState.IMAGE1_QUEUED
                                if retry_run.stage == GenerationStage.IMAGE1
                                else QuestionState.IMAGE2_QUEUED
                            )
                        if retry_batch and retry_batch.status != BatchStatus.PAUSED:
                            retry_batch.status = BatchStatus.RUNNING
                    session.commit()
                if (
                    not replacement
                    and provider_error.category == ProviderErrorCategory.RATE_LIMIT
                ):
                    raise RetryTask(delay_seconds)
                if not replacement:
                    setattr(provider_error, "credential_failure_recorded", True)
                    raise
                replacement_credential, replacement_key = replacement
                credential_id = replacement_credential.id
                provider = provider_factory(profile, replacement_key)
        prepared = [(index, await source_bytes(source)) for index, source in enumerate(result.images, 1)]
        with Session(app.state.engine, expire_on_commit=False) as session:
            task = session.get(GenerationTask, task_id)
            run = session.get(GenerationRun, task.run_id) if task else None
            question = session.get(Question, run.question_id) if run else None
            profile = session.get(ProviderProfile, task.provider_profile_id) if task else None
            if not task or not run or not question or not profile:
                return
            if run.stage == GenerationStage.IMAGE2 and question.selected_image1_id != run.reference_asset_id:
                task.status = TaskStatus.FAILED
                task.error_category = "stale_reference"
                task.error_message_safe = "第一张图在生成期间发生变化，结果已丢弃"
                task.finished_at = datetime.now(UTC)
                session.flush()
                finalize_task(session, task.id)
                session.commit()
                return
            project = session.get(Project, question.project_id)
            if not project:
                return
            layout = WorkspaceLayout(Path(project.workspace_path))
            layout.ensure()
            task.status = TaskStatus.SAVING
            task.provider_request_id = result.provider_request_id
            session.flush()
            stored_count = 0
            for output_index, data in prepared:
                asset_id = new_id()
                filename = candidate_name(
                    question.code, run.stage, task.request_index, output_index, asset_id
                )
                stored = store_image_atomic(data, layout.candidate_dir(run.stage) / filename)
                session.add(
                    ImageAsset(
                        id=asset_id,
                        task_id=task.id,
                        question_id=question.id,
                        stage=run.stage,
                        output_index=output_index,
                        local_path=str(stored.path),
                        sha256=stored.sha256,
                        width=stored.width,
                        height=stored.height,
                        mime_type=stored.mime_type,
                        file_size=stored.file_size,
                        reference_asset_id=run.reference_asset_id,
                        prompt_snapshot=run.prompt_snapshot,
                        provider=profile.provider,
                        model=profile.model_id,
                    )
                )
                stored_count += 1
            session.flush()
            credential = session.get(ProviderCredential, credential_id)
            if credential:
                try:
                    unit_price = float(
                        model_registry.get(profile.provider, profile.model_id).unit_price_cny
                    )
                except KeyError:
                    unit_price = float((profile.config or {}).get("unit_price_cny", 0))
                record_credential_success(
                    session, credential, task, stored_count, unit_price
                )
            task.retry_not_before = None
            task.error_category = None
            task.error_message_safe = None
            finished_run = mark_task_succeeded(session, task, stored_count)
            queued: list[str] = []
            if finished_run.stage == GenerationStage.IMAGE1:
                next_run = session.scalar(
                    select(GenerationRun).where(
                        GenerationRun.batch_id == finished_run.batch_id,
                        GenerationRun.question_id == finished_run.question_id,
                        GenerationRun.stage == GenerationStage.IMAGE2,
                    )
                )
                if next_run:
                    queued = list(
                        session.scalars(
                            select(GenerationTask.id).where(
                                GenerationTask.run_id == next_run.id,
                                GenerationTask.status == TaskStatus.QUEUED,
                            )
                        ).all()
                    )
            batch = session.get(GenerationBatch, finished_run.batch_id)
            paused = bool(batch and batch.status == BatchStatus.PAUSED)
            session.commit()
        for queued_id in queued:
            if not paused:
                await app.state.scheduler.submit(queued_id)
    except RetryTask:
        raise
    except (ProviderError, InvalidImageError, httpx.HTTPError) as error:
        with Session(app.state.engine, expire_on_commit=False) as session:
            task = session.get(GenerationTask, task_id)
            if not task:
                return
            task.status = TaskStatus.FAILED
            task.error_category = getattr(error, "category", "provider_error")
            task.error_message_safe = getattr(error, "safe_message", str(error))[:500]
            task.finished_at = datetime.now(UTC)
            credential = session.get(ProviderCredential, credential_id)
            if (
                credential
                and isinstance(error, ProviderError)
                and not getattr(error, "credential_failure_recorded", False)
            ):
                record_credential_failure(
                    session, credential, error.category, error.safe_message
                )
            session.flush()
            finalize_task(session, task.id)
            session.commit()
    except Exception:
        with Session(app.state.engine, expire_on_commit=False) as session:
            task = session.get(GenerationTask, task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_category = "internal"
                task.error_message_safe = "处理图片时发生内部错误，请重试"
                task.finished_at = datetime.now(UTC)
                session.flush()
                finalize_task(session, task.id)
                session.commit()
