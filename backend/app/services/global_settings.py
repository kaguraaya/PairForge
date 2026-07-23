from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppSettings, Project, ProviderProfile


GLOBAL_SETTINGS_ID = 1


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
