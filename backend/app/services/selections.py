from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import ImageAsset, Question
from app.domain.enums import GenerationStage, QuestionState
from app.domain.errors import (
    CrossQuestionReferenceError,
    InvalidStateTransitionError,
    MissingReferenceImageError,
    StaleReferenceImageError,
)


def _asset_for_question(
    session: Session, question: Question, asset_id: str, stage: GenerationStage
) -> ImageAsset:
    asset = session.get(ImageAsset, asset_id)
    if asset is None:
        raise MissingReferenceImageError("找不到指定图片")
    if asset.question_id != question.id:
        raise CrossQuestionReferenceError("不能选择其他题目的图片")
    if asset.stage != stage:
        raise InvalidStateTransitionError("图片阶段不匹配")
    if asset.stale:
        raise StaleReferenceImageError("图片引用已经失效")
    return asset


def select_image1(session: Session, question_id: str, asset_id: str) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise InvalidStateTransitionError("题目不存在")
    asset = _asset_for_question(session, question, asset_id, GenerationStage.IMAGE1)
    previous_id = question.selected_image1_id
    session.execute(
        update(ImageAsset)
        .where(ImageAsset.question_id == question.id, ImageAsset.stage == GenerationStage.IMAGE1)
        .values(selected=False)
    )
    asset.selected = True
    question.selected_image1_id = asset.id

    if previous_id != asset.id:
        second_images = session.scalars(
            select(ImageAsset).where(
                ImageAsset.question_id == question.id,
                ImageAsset.stage == GenerationStage.IMAGE2,
            )
        ).all()
        for second in second_images:
            if second.reference_asset_id != asset.id:
                second.stale = True
                second.selected = False
        if question.selected_image2_id:
            selected_second = session.get(ImageAsset, question.selected_image2_id)
            if not selected_second or selected_second.reference_asset_id != asset.id:
                question.selected_image2_id = None
    question.state = QuestionState.IMAGE2_READY
    session.flush()
    return question


def select_image2(session: Session, question_id: str, asset_id: str) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise InvalidStateTransitionError("题目不存在")
    if not question.selected_image1_id:
        raise MissingReferenceImageError("必须先选择第一张图")
    asset = _asset_for_question(session, question, asset_id, GenerationStage.IMAGE2)
    if asset.reference_asset_id != question.selected_image1_id:
        raise StaleReferenceImageError("第二张图不是基于当前第一张图生成的")
    session.execute(
        update(ImageAsset)
        .where(ImageAsset.question_id == question.id, ImageAsset.stage == GenerationStage.IMAGE2)
        .values(selected=False)
    )
    asset.selected = True
    question.selected_image2_id = asset.id
    question.state = QuestionState.COMPLETED
    session.flush()
    return question

