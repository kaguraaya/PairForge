from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppSettings,
    GenerationTask,
    Project,
    ProviderProfile,
)
from app.domain.enums import TaskStatus
from app.domain.errors import InvalidStateTransitionError
from app.security.secrets import SecretStore
from app.services.credentials import credentials_for_profile, disable_credential


GLOBAL_SETTINGS_ID = 1
ACTIVE_TASK_STATUSES = {
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.SAVING,
}


def get_global_settings(session: Session) -> AppSettings:
    settings = session.get(AppSettings, GLOBAL_SETTINGS_ID)
    if settings:
        return settings
    projects = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    q1_prompt_suffix = next(
        (project.q1_prompt_suffix for project in projects if project.q1_prompt_suffix.strip()),
        "",
    )
    q2_prompt_suffix = next(
        (project.q2_prompt_suffix for project in projects if project.q2_prompt_suffix.strip()),
        "",
    )
    settings = AppSettings(
        id=GLOBAL_SETTINGS_ID,
        q1_prompt_suffix=q1_prompt_suffix,
        q2_prompt_suffix=q2_prompt_suffix,
    )
    session.add(settings)
    session.flush()
    return settings


def initialize_global_configuration(session: Session) -> AppSettings:
    settings = get_global_settings(session)
    profiles = session.scalars(
        select(ProviderProfile).where(ProviderProfile.project_id.is_not(None))
    ).all()
    for profile in profiles:
        profile.project_id = None
    session.flush()
    return settings


def update_global_prompts(
    session: Session,
    q1_prompt_suffix: str,
    q2_prompt_suffix: str,
) -> AppSettings:
    settings = get_global_settings(session)
    settings.q1_prompt_suffix = q1_prompt_suffix
    settings.q2_prompt_suffix = q2_prompt_suffix
    session.flush()
    return settings


def archive_provider_profile(
    session: Session,
    secret_store: SecretStore,
    profile: ProviderProfile,
) -> tuple[ProviderProfile | None, int]:
    active_task = session.scalar(
        select(GenerationTask.id)
        .where(
            GenerationTask.provider_profile_id == profile.id,
            GenerationTask.status.in_(ACTIVE_TASK_STATUSES),
        )
        .limit(1)
    )
    if active_task:
        raise InvalidStateTransitionError(
            "该服务仍有排队或生成中的任务，请先暂停并等待在途任务结束"
        )
    for credential in credentials_for_profile(session, profile.id):
        disable_credential(session, secret_store, profile, credential.id)
    profile.archived = True
    replacement = session.scalar(
        select(ProviderProfile)
        .where(
            ProviderProfile.id != profile.id,
            ProviderProfile.archived.is_(False),
        )
        .order_by(ProviderProfile.updated_at.desc())
    )
    affected_projects = session.scalars(
        select(Project).where(Project.selected_provider_profile_id == profile.id)
    ).all()
    for project in affected_projects:
        project.selected_provider_profile_id = replacement.id if replacement else None
    session.flush()
    return replacement, len(affected_projects)
