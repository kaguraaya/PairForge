import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Project
from app.services.exporter import ExportValidationError, export_project

router = APIRouter(prefix="/api/exports", tags=["exports"])


class ExportRequest(BaseModel):
    project_id: str


class OpenFolderRequest(BaseModel):
    path: str


@router.post("")
def create_export(
    body: ExportRequest, session: Session = Depends(get_session)
) -> dict[str, object]:
    project = session.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    try:
        result = export_project(session, project.id, Path(project.workspace_path) / "exports")
    except ExportValidationError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    session.commit()
    return {
        "directory": str(result.directory),
        "images_directory": str(result.images_directory),
        "question_count": result.question_count,
        "image_count": result.image_count,
    }


@router.post("/open-folder")
def open_folder(body: OpenFolderRequest, request: Request) -> dict[str, bool]:
    path = Path(body.path).resolve()
    data_root = request.app.state.config.data_dir.resolve()
    if (
        not path.is_dir()
        or not path.is_relative_to(data_root)
        or "exports" not in {part.lower() for part in path.parts}
    ):
        raise HTTPException(400, "只能打开已生成的导出目录")
    os.startfile(path)  # type: ignore[attr-defined]
    return {"opened": True}
