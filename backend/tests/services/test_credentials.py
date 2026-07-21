from datetime import UTC, datetime, timedelta

from app.db.models import ProviderCredential, ProviderProfile
from app.domain.enums import CredentialStatus
from app.security.secrets import SecretStore
from app.services.credentials import available_credentials, save_credential


def profile(session, provider: str, name: str) -> ProviderProfile:
    item = ProviderProfile(
        provider=provider,
        display_name=name,
        base_url="https://example.invalid",
        model_id="model",
    )
    session.add(item)
    session.flush()
    return item


def test_credentials_never_cross_provider_profiles_and_follow_priority(session) -> None:
    volc = profile(session, "volcengine", "Volc")
    ali = profile(session, "alibaba", "Ali")
    session.add_all(
        [
            ProviderCredential(
                profile_id=volc.id, label="备用", priority=20, secret_configured=True
            ),
            ProviderCredential(
                profile_id=volc.id, label="主用", priority=10, secret_configured=True
            ),
            ProviderCredential(
                profile_id=ali.id, label="阿里", priority=1, secret_configured=True
            ),
        ]
    )
    session.flush()
    selected = available_credentials(session, volc.id)
    assert [item.label for item in selected] == ["主用", "备用"]
    assert all(item.profile_id == volc.id for item in selected)


def test_unavailable_credentials_are_skipped_and_expired_cooldown_recovers(session) -> None:
    item = profile(session, "volcengine", "Volc")
    now = datetime.now(UTC)
    session.add_all(
        [
            ProviderCredential(
                profile_id=item.id,
                label="耗尽",
                priority=1,
                secret_configured=True,
                status=CredentialStatus.EXHAUSTED,
            ),
            ProviderCredential(
                profile_id=item.id,
                label="预算为零",
                priority=2,
                secret_configured=True,
                manual_remaining_images=0,
            ),
            ProviderCredential(
                profile_id=item.id,
                label="冷却结束",
                priority=3,
                secret_configured=True,
                status=CredentialStatus.COOLDOWN,
                cooldown_until=now - timedelta(seconds=1),
            ),
        ]
    )
    session.flush()
    selected = available_credentials(session, item.id, now=now)
    assert [credential.label for credential in selected] == ["冷却结束"]
    assert selected[0].status == CredentialStatus.ACTIVE


def test_manual_budget_zero_and_refill_update_credential_state(session) -> None:
    item = profile(session, "volcengine", "Volc")
    secret_store = SecretStore()
    credential, _ = save_credential(
        session,
        secret_store,
        item,
        credential_id=None,
        label="主 Key",
        api_key="test-secret-1234",
        manual_remaining_images=0,
    )
    assert credential.status == CredentialStatus.EXHAUSTED
    assert available_credentials(session, item.id) == []

    credential, _ = save_credential(
        session,
        secret_store,
        item,
        credential_id=credential.id,
        label="主 Key",
        manual_remaining_images=5,
    )
    assert credential.status == CredentialStatus.ACTIVE
    assert available_credentials(session, item.id) == [credential]
