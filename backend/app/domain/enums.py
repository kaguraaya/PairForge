from enum import StrEnum


class GenerationStage(StrEnum):
    IMAGE1 = "image1"
    IMAGE2 = "image2"


class QuestionState(StrEnum):
    IMPORTED = "imported"
    IMAGE1_QUEUED = "image1_queued"
    IMAGE1_RUNNING = "image1_running"
    IMAGE1_REVIEW = "image1_review"
    IMAGE1_SELECTED = "image1_selected"
    IMAGE2_READY = "image2_ready"
    IMAGE2_QUEUED = "image2_queued"
    IMAGE2_RUNNING = "image2_running"
    IMAGE2_REVIEW = "image2_review"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"


class BatchStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SAVING = "saving"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class OutputSemantics(StrEnum):
    FIXED = "fixed"
    EXACT = "exact"
    MAXIMUM = "maximum"


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    EXHAUSTED = "exhausted"
    INVALID = "invalid"
    DISABLED = "disabled"
