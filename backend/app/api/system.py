from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.meta import APP_DESCRIPTION, APP_NAME, APP_VERSION, REPOSITORY_URL


router = APIRouter(prefix="/api/system", tags=["system"])


class OpenDirectoryRequest(BaseModel):
    path: str


def cache_usage(cache_dir: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    if not cache_dir.exists():
        return file_count, total_bytes
    for path in cache_dir.rglob("*"):
        if not path.is_file():
            continue
        file_count += 1
        try:
            total_bytes += path.stat().st_size
        except FileNotFoundError:
            continue
    return file_count, total_bytes


def clear_cache_directory(cache_dir: Path) -> tuple[int, int]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_count, total_bytes = cache_usage(cache_dir)
    for child in tuple(cache_dir.iterdir()):
        try:
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        except FileNotFoundError:
            continue
    return file_count, total_bytes


@router.get("/info")
def system_info(request: Request) -> dict[str, object]:
    config = request.app.state.config
    file_count, total_bytes = cache_usage(config.cache_dir)
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": APP_DESCRIPTION,
        "repository_url": REPOSITORY_URL,
        "data_directory": str(config.data_dir),
        "projects_directory": str(config.data_dir / "projects"),
        "cache_directory": str(config.cache_dir),
        "cache_file_count": file_count,
        "cache_bytes": total_bytes,
    }


@router.post("/cache/clear")
def clear_cache(request: Request) -> dict[str, object]:
    file_count, total_bytes = clear_cache_directory(request.app.state.config.cache_dir)
    return {
        "cleared_file_count": file_count,
        "cleared_bytes": total_bytes,
    }


def is_user_data_directory(path: Path, data_root: Path) -> bool:
    if path == data_root:
        return True
    projects_root = data_root / "projects"
    if path == projects_root:
        return True
    try:
        relative = path.relative_to(projects_root)
    except ValueError:
        return False
    parts = relative.parts
    if len(parts) == 1:
        return True
    return len(parts) >= 2 and parts[1].lower() in {"assets", "exports"}


@router.post("/directory/open")
def open_directory(body: OpenDirectoryRequest, request: Request) -> dict[str, bool]:
    data_root = request.app.state.config.data_dir.resolve()
    path = Path(body.path).expanduser().resolve()
    if not is_user_data_directory(path, data_root):
        raise HTTPException(400, "只能打开 PairForge 的数据、候选图或导出目录")
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)  # type: ignore[attr-defined]
    return {"opened": True}
