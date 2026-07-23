from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Project, ProviderProfile, Question
from app.importers.dispatcher import parse_question_bank

router = APIRouter(prefix="/api/imports", tags=["imports"])
ALLOWED_EXTENSIONS = {".docx", ".doc", ".md", ".markdown"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024


class ConfirmImport(BaseModel):
    token: str
    project_name: str


def preview_payload(preview, token: str) -> dict[str, object]:
    return {
        "token": token,
        "source_name": preview.source_name,
        "source_sha256": preview.source_sha256,
        "recognized_count": len(preview.questions),
        "complete_count": preview.complete_count,
        "warning_count": preview.warning_count,
        "error_count": preview.error_count,
        "questions": [item.model_dump() for item in preview.questions],
        "issues": [item.model_dump() for item in preview.issues],
    }


def validate_docx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 10_000:
                raise HTTPException(400, "DOCX 内部文件数量异常")
            uncompressed = sum(item.file_size for item in entries)
            if uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(400, "DOCX 解压后体积过大")
    except zipfile.BadZipFile as error:
        raise HTTPException(400, "DOCX 文件结构无效") from error


@router.post("/preview")
async def preview_import(request: Request, file: UploadFile = File(...)) -> dict[str, object]:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "仅支持 DOCX、DOC 和 Markdown 题库")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "题库文件超过 50MB")
    if extension == ".docx":
        validate_docx_archive(data)
    token = hashlib.sha256(data).hexdigest()
    upload_dir: Path = request.app.state.config.cache_dir / "imports"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{token}{extension}"
    if not path.exists():
        path.write_bytes(data)
    try:
        preview = parse_question_bank(path, upload_dir / "converted")
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    return preview_payload(preview, token)


@router.post("/confirm")
def confirm_import(
    body: ConfirmImport,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    upload_dir: Path = request.app.state.config.cache_dir / "imports"
    matches = list(upload_dir.glob(f"{body.token}.*"))
    source = next((path for path in matches if path.suffix.lower() in ALLOWED_EXTENSIONS), None)
    if source is None:
        raise HTTPException(404, "导入预览已失效，请重新选择文件")
    preview = parse_question_bank(source, upload_dir / "converted")
    if preview.error_count:
        raise HTTPException(409, "题库仍有严重错误，不能确认导入")
    existing = session.scalar(select(Project).where(Project.source_sha256 == preview.source_sha256))
    if existing:
        return {"project_id": existing.id, "question_count": len(preview.questions), "reused": True}
    project = Project(name=body.project_name.strip() or source.stem, workspace_path="")
    project.source_sha256 = preview.source_sha256
    default_profile = session.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.project_id.is_(None))
        .order_by(ProviderProfile.updated_at.desc())
    )
    if default_profile:
        project.selected_provider_profile_id = default_profile.id
    session.add(project)
    session.flush()
    project_root = request.app.state.config.data_dir / "projects" / project.id
    project_root.mkdir(parents=True, exist_ok=True)
    project.workspace_path = str(project_root)
    for parsed in preview.questions:
        session.add(Question(project_id=project.id, **parsed.model_dump(exclude={"extra_fields"})))
    session.commit()
    return {"project_id": project.id, "question_count": len(preview.questions), "reused": False}
