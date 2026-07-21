from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.imports import ImportIssue, ParsedQuestion


FIELD_MAP = {
    "基本信息": "basic_info",
    "图1生图提示词": "image1_prompt",
    "图1题面提示": "image1_clue",
    "图2生图提示词": "image2_prompt",
    "图2题面填空": "image2_fill",
    "答案": "answer",
    "数字声调拼音": "pinyin",
    "谜底拆解": "explanation",
}
REQUIRED_LABELS = tuple(FIELD_MAP)
TITLE_RE = re.compile(r"^(?P<code>\d{3})\s*[｜|]\s*(?P<title>.+?)\s*$")
PRIORITY_MARKER = "★优先盲测"


def normalized_label(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("：:")


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class QuestionBuilder:
    code: str
    title: str
    priority_blind_test: bool = False
    group_name: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    quality_parts: list[str] = field(default_factory=list)
    extra_fields: dict[str, str] = field(default_factory=dict)

    def set_field(self, label: str, value: str, issues: list[ImportIssue]) -> None:
        if label in self.fields:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="DUPLICATE_FIELD",
                    message=f"题目 {self.code} 的字段“{label}”出现多次。",
                    question_code=self.code,
                    field=label,
                )
            )
            return
        self.fields[label] = value.strip()

    def add_unknown_field(self, label: str, value: str, issues: list[ImportIssue]) -> None:
        self.extra_fields[label] = value.strip()
        issues.append(
            ImportIssue(
                severity="warning",
                code="UNKNOWN_FIELD",
                message=f"题目 {self.code} 包含尚未识别的字段“{label}”。",
                question_code=self.code,
                field=label,
            )
        )

    def build(self) -> ParsedQuestion:
        basic = parse_basic_info(self.fields.get("基本信息", ""))
        return ParsedQuestion(
            code=self.code,
            title=self.title,
            group_name=self.group_name,
            question_type=basic.get("question_type"),
            difficulty=basic.get("difficulty"),
            answer_length=basic.get("answer_length"),
            source=basic.get("source"),
            priority_blind_test=self.priority_blind_test,
            image1_prompt=self.fields.get("图1生图提示词", ""),
            image1_clue=self.fields.get("图1题面提示", ""),
            image2_prompt=self.fields.get("图2生图提示词", ""),
            image2_fill=self.fields.get("图2题面填空", ""),
            answer=self.fields.get("答案", ""),
            pinyin=self.fields.get("数字声调拼音", ""),
            explanation=self.fields.get("谜底拆解", ""),
            quality_check="\n".join(self.quality_parts).strip(),
            extra_fields=self.extra_fields,
        )


def parse_title(text: str) -> tuple[str, str, bool] | None:
    match = TITLE_RE.match(text.strip())
    if not match:
        return None
    title = match.group("title").strip()
    priority = PRIORITY_MARKER in title
    title = title.replace(PRIORITY_MARKER, "").strip()
    return match.group("code"), title, priority


def parse_basic_info(value: str) -> dict[str, str | int | None]:
    result: dict[str, str | int | None] = {
        "question_type": None,
        "difficulty": None,
        "answer_length": None,
        "source": None,
    }
    key_map = {
        "类型": "question_type",
        "难度": "difficulty",
        "答案字数": "answer_length",
        "出处": "source",
        "所属作品或出处": "source",
    }
    for part in re.split(r"\s*[｜|]\s*", value.strip()):
        if not part:
            continue
        pieces = re.split(r"\s*[:：]\s*", part, maxsplit=1)
        if len(pieces) != 2:
            continue
        key, raw = pieces[0].strip(), pieces[1].strip()
        target = key_map.get(key)
        if target == "answer_length":
            match = re.search(r"\d+", raw)
            result[target] = int(match.group()) if match else None
        elif target:
            result[target] = raw
    return result

