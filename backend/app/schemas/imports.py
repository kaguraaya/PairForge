from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning"]
    code: str
    message: str
    question_code: str | None = None
    field: str | None = None


class ParsedQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    group_name: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    answer_length: int | None = None
    source: str | None = None
    priority_blind_test: bool = False
    image1_prompt: str = ""
    image1_clue: str = ""
    image2_prompt: str = ""
    image2_fill: str = ""
    answer: str = ""
    pinyin: str = ""
    explanation: str = ""
    quality_check: str = ""
    extra_fields: dict[str, str] = Field(default_factory=dict)


class ImportPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_name: str = ""
    source_sha256: str = ""
    questions: tuple[ParsedQuestion, ...] = ()
    issues: tuple[ImportIssue, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def complete_count(self) -> int:
        error_codes = {
            issue.question_code
            for issue in self.issues
            if issue.severity == "error" and issue.question_code
        }
        return sum(question.code not in error_codes for question in self.questions)

