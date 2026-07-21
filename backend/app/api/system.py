from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Request

from app.meta import APP_DESCRIPTION, APP_NAME, APP_VERSION, REPOSITORY_URL


router = APIRouter(prefix="/api/system", tags=["system"])


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
