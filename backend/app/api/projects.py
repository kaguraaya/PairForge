from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Project, Question

router = APIRouter(prefix="/api/projects", tags=["projects"])


class PromptSettings(BaseModel):
    q1_prompt_suffix: str = ""
    q2_prompt_suffix: str = ""


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
    return {
        "id": project.id,
        "name": project.name,
        "workspace_path": project.workspace_path,
        "q1_prompt_suffix": project.q1_prompt_suffix,
        "q2_prompt_suffix": project.q2_prompt_suffix,
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
    project.q1_prompt_suffix = body.q1_prompt_suffix
    project.q2_prompt_suffix = body.q2_prompt_suffix
    session.commit()
    return {"q1_prompt_suffix": project.q1_prompt_suffix, "q2_prompt_suffix": project.q2_prompt_suffix}

