from datetime import UTC, datetime, timedelta

from app.db.models import Project, ProviderCredential, ProviderProfile
from app.services.global_settings import initialize_global_configuration


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
