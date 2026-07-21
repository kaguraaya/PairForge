from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import GenerationRun, GenerationTask, ImageAsset, Question
from app.domain.enums import TaskStatus

router = APIRouter(prefix="/api", tags=["questions"])


def asset_payload(asset: ImageAsset) -> dict[str, object]:
    return {
        "id": asset.id,
        "stage": asset.stage,
        "output_index": asset.output_index,
        "url": f"/api/assets/{asset.id}",
        "selected": asset.selected,
        "stale": asset.stale,
        "reference_asset_id": asset.reference_asset_id,
        "width": asset.width,
        "height": asset.height,
    }


@router.get("/projects/{project_id}/questions")
def list_questions(project_id: str, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    questions = session.scalars(
        select(Question).where(Question.project_id == project_id).order_by(Question.code)
    ).all()
    result = []
    for question in questions:
        assets = session.scalars(
            select(ImageAsset).where(ImageAsset.question_id == question.id).order_by(
                ImageAsset.stage, ImageAsset.output_index
            )
        ).all()
        latest_task = session.scalar(
            select(GenerationTask)
            .join(GenerationRun, GenerationTask.run_id == GenerationRun.id)
            .where(GenerationRun.question_id == question.id)
            .order_by(GenerationTask.created_at.desc())
        )
        result.append(
            {
                "id": question.id,
                "code": question.code,
                "title": question.title,
                "answer": question.answer,
                "state": question.state,
                "priority_blind_test": question.priority_blind_test,
                "image1_prompt": question.image1_prompt,
                "image2_prompt": question.image2_prompt,
                "selected_image1_id": question.selected_image1_id,
                "selected_image2_id": question.selected_image2_id,
                "latest_failed_task_id": (
                    latest_task.id
                    if latest_task
                    and latest_task.status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED}
                    else None
                ),
                "latest_error": latest_task.error_message_safe if latest_task else None,
                "latest_error_category": latest_task.error_category if latest_task else None,
                "assets": [asset_payload(asset) for asset in assets],
            }
        )
    return result


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, session: Session = Depends(get_session)):
    from fastapi.responses import FileResponse

    asset = session.get(ImageAsset, asset_id)
    if not asset:
        raise HTTPException(404, "图片不存在")
    return FileResponse(asset.local_path, media_type=asset.mime_type)


@router.get("/tasks")
def list_tasks(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    tasks = session.scalars(select(GenerationTask).order_by(GenerationTask.created_at.desc()).limit(200)).all()
    return [
        {
            "id": task.id,
            "run_id": task.run_id,
            "status": task.status,
            "actual_output_count": task.actual_output_count,
            "error_message_safe": task.error_message_safe,
            "run": session.get(GenerationRun, task.run_id).stage,
        }
        for task in tasks
    ]
