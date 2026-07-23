from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import (
    GenerationTask,
    Project,
    ProviderCredential,
    ProviderProfile,
)
from app.domain.enums import TaskStatus
from app.domain.errors import InvalidStateTransitionError
from app.security.secrets import SecretStore
from app.services.global_settings import (
    archive_provider_profile,
    initialize_global_configuration,
)
from tests.factories import create_task_context


def test_legacy_project_settings_become_global_without_changing_ids(session) -> None:
    older = Project(
        name="旧项目",
        workspace_path="C:/older",
        q1_prompt_suffix="旧图一",
        q2_prompt_suffix="",
        updated_at=datetime.now(UTC) - timedelta(days=1),
    )
    newer = Project(
        name="新项目",
        workspace_path="C:/newer",
        q1_prompt_suffix="新图一",
        q2_prompt_suffix="新图二",
        updated_at=datetime.now(UTC),
    )
    session.add_all([older, newer])
    session.flush()
    profile = ProviderProfile(
        project_id=older.id,
        provider="custom",
        display_name="原服务",
        base_url="https://example.invalid",
        model_id="model",
    )
    session.add(profile)
    session.flush()
    credential = ProviderCredential(
        profile_id=profile.id,
        label="主 Key",
        priority=10,
    )
    session.add(credential)
    older.selected_provider_profile_id = profile.id
    session.flush()
    older.updated_at = datetime.now(UTC) - timedelta(days=1)
    newer.updated_at = datetime.now(UTC)
    session.flush()
    profile_id = profile.id
    credential_id = credential.id

    settings = initialize_global_configuration(session)

    assert profile.id == profile_id
    assert profile.project_id is None
    assert credential.id == credential_id
    assert credential.profile_id == profile_id
    assert older.selected_provider_profile_id == profile_id
    assert settings.q1_prompt_suffix == "新图一"
    assert settings.q2_prompt_suffix == "新图二"


def test_profile_with_active_task_cannot_be_archived(session) -> None:
    run, profile = create_task_context(session)
    task = GenerationTask(
        run_id=run.id,
        provider_profile_id=profile.id,
        model_id=profile.model_id,
        request_index=1,
        idempotency_key="active-service-delete",
        status=TaskStatus.RUNNING,
    )
    session.add(task)
    session.flush()

    with pytest.raises(InvalidStateTransitionError, match="排队或生成中"):
        archive_provider_profile(session, SecretStore(), profile)

    assert profile.archived is False

    task.status = TaskStatus.SUCCEEDED
    replacement, affected_count = archive_provider_profile(
        session,
        SecretStore(),
        profile,
    )
    assert replacement is None
    assert affected_count == 0
    assert profile.archived is True
