from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session

from app.api import events, exports, generation, imports, projects, questions, settings, system
from app.config import AppConfig, default_data_dir
from app.db.base import Base
from app.db.migrations import ensure_schema_compatibility
from app.db.session import create_sqlite_engine, database_url
from app.queue.recovery import recover_interrupted_tasks
from app.queue.scheduler import TaskScheduler
from app.security.secrets import SecretStore
from app.services.worker import execute_task
from app.services.credentials import migrate_legacy_credentials, reconcile_persisted_credentials
from app.services.global_settings import initialize_global_configuration
from app.meta import APP_NAME, APP_VERSION


def bundled_frontend() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "frontend" / "dist"


def create_app(data_dir: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    config = AppConfig((data_dir or default_data_dir()).resolve())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        engine = create_sqlite_engine(database_url(config.data_dir / "workbench.sqlite3"))
        Base.metadata.create_all(engine)
        ensure_schema_compatibility(engine)
        application.state.config = config
        application.state.engine = engine
        application.state.secret_store = SecretStore()
        scheduler = TaskScheduler(lambda task_id: execute_task(application, task_id), concurrency=8)
        application.state.scheduler = scheduler
        await scheduler.start()
        with Session(engine) as session:
            initialize_global_configuration(session)
            migrate_legacy_credentials(session, application.state.secret_store)
            reconcile_persisted_credentials(session, application.state.secret_store)
            queued, _interrupted = recover_interrupted_tasks(session)
            session.commit()
        for task_id, delay_seconds in queued:
            await scheduler.submit(task_id, delay_seconds)
        try:
            yield
        finally:
            await scheduler.stop()
            engine.dispose()

    application = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        return response
    application.include_router(imports.router)
    application.include_router(projects.router)
    application.include_router(questions.router)
    application.include_router(settings.router)
    application.include_router(generation.router)
    application.include_router(exports.router)
    application.include_router(events.router)
    application.include_router(system.router)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    frontend = static_dir or bundled_frontend()
    if frontend.is_dir():
        application.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return application


app = create_app()
