from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Question
from app.providers.base import ModelCapabilities


@dataclass(frozen=True, slots=True)
class QuotaEstimate:
    question_count: int
    image1_maximum: int
    image2_maximum: int
    total_maximum: int
    estimated_cost_cny: Decimal
    actual_may_be_lower: bool


def estimate_range(
    session: Session,
    project_id: str,
    start_code: str,
    end_code: str,
    q1_outputs: int,
    q2_outputs: int,
    capabilities: ModelCapabilities,
) -> QuotaEstimate:
    if q1_outputs < 1 or q1_outputs > capabilities.max_text_outputs:
        raise ValueError("第一张图候选数量超出模型范围")
    if q2_outputs < 1 or q2_outputs > capabilities.max_edit_outputs:
        raise ValueError("第二张图候选数量超出模型范围")
    questions = session.scalars(
        select(Question).where(
            Question.project_id == project_id,
            Question.code >= start_code,
            Question.code <= end_code,
        )
    ).all()
    count = len(questions)
    image1 = count * q1_outputs
    image2 = count * q2_outputs
    total = image1 + image2
    variable = capabilities.multiple_output_semantics.value == "maximum" and (
        q1_outputs > 1 or q2_outputs > 1
    )
    return QuotaEstimate(
        count,
        image1,
        image2,
        total,
        capabilities.unit_price_cny * total,
        variable,
    )

