from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Project, ProviderProfile, Question
from app.services.global_settings import get_global_settings, update_global_prompts

router = APIRouter(prefix="/api/projects", tags=["projects"])


class PromptSettings(BaseModel):
    q1_prompt_suffix: str = ""
    q2_prompt_suffix: str = ""


class ProviderSelection(BaseModel):
    profile_id: str


@router.get("")
def list_projects(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    projects = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return [
        {
            "id": project.id,
            "name": project.name,
            "question_count": session.scalar(
                select(func.count()).select_from(Question).where(Question.project_id == project.id)
            ),
            "updated_at": project.updated_at,
        }
        for project in projects
    ]


@router.get("/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    global_settings = get_global_settings(session)
    return {
        "id": project.id,
        "name": project.name,
        "workspace_path": project.workspace_path,
        "candidate_images_directory": str(Path(project.workspace_path) / "assets"),
        "exports_directory": str(Path(project.workspace_path) / "exports"),
        "q1_prompt_suffix": global_settings.q1_prompt_suffix,
        "q2_prompt_suffix": global_settings.q2_prompt_suffix,
        "selected_provider_profile_id": project.selected_provider_profile_id,
    }


@router.put("/{project_id}/prompts")
def update_prompts(
    project_id: str,
    body: PromptSettings,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    settings = update_global_prompts(
        session,
        body.q1_prompt_suffix,
        body.q2_prompt_suffix,
    )
    session.commit()
    return {
        "q1_prompt_suffix": settings.q1_prompt_suffix,
        "q2_prompt_suffix": settings.q2_prompt_suffix,
    }


@router.put("/{project_id}/provider-profile")
def select_provider_profile(
    project_id: str,
    body: ProviderSelection,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    profile = session.get(ProviderProfile, body.profile_id)
    if not profile:
        raise HTTPException(404, "生图服务配置不存在")
    if profile.project_id not in {None, project.id}:
        raise HTTPException(409, "该服务尚未迁移为全局配置")
    profile.project_id = None
    profile.updated_at = datetime.now(UTC)
    project.selected_provider_profile_id = profile.id
    session.commit()
    return {"selected_provider_profile_id": profile.id}
