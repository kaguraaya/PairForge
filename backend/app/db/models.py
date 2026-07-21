from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import (
    BatchStatus,
    CredentialStatus,
    GenerationStage,
    OutputSemantics,
    QuestionState,
    RunStatus,
    TaskStatus,
)


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    q1_prompt_suffix: Mapped[str] = mapped_column(Text, default="", nullable=False)
    q2_prompt_suffix: Mapped[str] = mapped_column(Text, default="", nullable=False)
    selected_provider_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )


class ProviderProfile(TimestampMixin, Base):
    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    secret_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    remember_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


class ProviderCredential(TimestampMixin, Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("profile_id", "label", name="uq_credential_profile_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    account_label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    secret_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    remember_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[CredentialStatus] = mapped_column(
        Enum(CredentialStatus, native_enum=False, length=30),
        default=CredentialStatus.ACTIVE,
        nullable=False,
    )
    manual_remaining_images: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_safe: Mapped[str | None] = mapped_column(Text, nullable=True)


class CredentialUsage(TimestampMixin, Base):
    __tablename__ = "credential_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("provider_credentials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_cny: Mapped[float | None] = mapped_column(Float, nullable=True)


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_question_project_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    question_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)
    answer_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    priority_blind_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image1_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image1_clue: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image2_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image2_fill: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answer: Mapped[str] = mapped_column(String(300), nullable=False)
    pinyin: Mapped[str] = mapped_column(Text, default="", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    quality_check: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[QuestionState] = mapped_column(
        Enum(QuestionState, native_enum=False, length=40),
        default=QuestionState.IMPORTED,
        nullable=False,
    )
    selected_image1_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="SET NULL"), nullable=True
    )
    selected_image2_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="SET NULL"), nullable=True
    )


class GenerationBatch(TimestampMixin, Base):
    __tablename__ = "generation_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    start_code: Mapped[str] = mapped_column(String(20), nullable=False)
    end_code: Mapped[str] = mapped_column(String(20), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    q1_requested_outputs: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    q2_requested_outputs: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    q1_output_semantics: Mapped[OutputSemantics] = mapped_column(
        Enum(OutputSemantics, native_enum=False, length=20), nullable=False
    )
    q2_output_semantics: Mapped[OutputSemantics] = mapped_column(
        Enum(OutputSemantics, native_enum=False, length=20), nullable=False
    )
    image1_maximum: Mapped[int] = mapped_column(Integer, nullable=False)
    image2_maximum: Mapped[int] = mapped_column(Integer, nullable=False)
    total_maximum: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_continue: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, native_enum=False, length=30), default=BatchStatus.DRAFT, nullable=False
    )


class GenerationRun(TimestampMixin, Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint("batch_id", "question_id", "stage", name="uq_run_batch_question_stage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("generation_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[GenerationStage] = mapped_column(
        Enum(GenerationStage, native_enum=False, length=20), nullable=False
    )
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    global_suffix: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    requested_outputs: Mapped[int] = mapped_column(Integer, nullable=False)
    output_semantics: Mapped[OutputSemantics] = mapped_column(
        Enum(OutputSemantics, native_enum=False, length=20), nullable=False
    )
    reference_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=30), default=RunStatus.QUEUED, nullable=False
    )


class GenerationTask(TimestampMixin, Base):
    __tablename__ = "generation_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    request_index: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=30), default=TaskStatus.QUEUED, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actual_output_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImageAsset(TimestampMixin, Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        UniqueConstraint("task_id", "output_index", name="uq_asset_task_output"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[GenerationStage] = mapped_column(
        Enum(GenerationStage, native_enum=False, length=20), nullable=False
    )
    output_index: Mapped[int] = mapped_column(Integer, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("image_assets.id", ondelete="RESTRICT"), nullable=True
    )
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
