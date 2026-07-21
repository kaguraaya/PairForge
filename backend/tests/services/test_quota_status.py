import httpx
import pytest

from app.db.models import ProviderProfile
from app.security.secrets import SecretStore
from app.services.credentials import save_credential
from app.services.quota_status import preflight_profile


@pytest.mark.asyncio
async def test_volcengine_preflight_reports_local_status_without_disclosing_secret(
    session,
) -> None:
    profile = ProviderProfile(
        provider="volcengine",
        display_name="Seedream",
        base_url="https://ark.cn-beijing.volces.com",
        model_id="doubao-seedream-5-0-lite-260128",
    )
    session.add(profile)
    session.flush()
    secret_store = SecretStore()
    credential, _ = save_credential(
        session,
        secret_store,
        profile,
        credential_id=None,
        label="主 Key",
        api_key="secret-that-must-never-leak-9876",
        remember_secret=False,
        manual_remaining_images=12,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ping"
        assert request.headers["Authorization"].endswith("9876")
        return httpx.Response(200, text="pong")

    result = await preflight_profile(
        session,
        secret_store,
        profile,
        transport_factory=lambda _credential: httpx.MockTransport(handler),
    )

    assert result["supports_non_billable_preflight"] is True
    assert result["available_credential_count"] == 1
    assert result["credentials"][0]["id"] == credential.id
    assert result["credentials"][0]["last_four"] == "9876"
    assert result["credentials"][0]["preflight_status"] == "ok"
    assert "secret-that-must-never-leak" not in repr(result)


@pytest.mark.asyncio
async def test_alibaba_preflight_is_truthful_console_only_and_makes_no_request(
    session,
) -> None:
    profile = ProviderProfile(
        provider="alibaba",
        display_name="Qwen",
        base_url="https://dashscope.aliyuncs.com",
        model_id="qwen-image-2.0",
    )
    session.add(profile)
    session.flush()
    secret_store = SecretStore()
    save_credential(
        session,
        secret_store,
        profile,
        credential_id=None,
        label="主 Key",
        api_key="alibaba-secret-4321",
        remember_secret=False,
    )

    result = await preflight_profile(session, secret_store, profile)

    assert result["supports_non_billable_preflight"] is False
    assert result["official_quota"]["kind"] == "shared_account_model"
    assert result["available_credential_count"] == 1
    assert result["credentials"][0]["preflight_status"] == "not_checked"
    assert "alibaba-secret" not in repr(result)
