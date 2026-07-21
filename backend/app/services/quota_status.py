from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CredentialUsage, ProviderCredential, ProviderProfile
from app.domain.enums import CredentialStatus
from app.providers.base import ProviderConfig
from app.providers.errors import ProviderError
from app.providers.volcengine import VolcengineProvider
from app.security.secrets import SecretStore
from app.services.credentials import (
    available_credentials,
    credential_payload,
    credentials_for_profile,
    record_credential_failure,
    sync_profile_summary,
)


OFFICIAL_QUOTA = {
    "volcengine": {
        "kind": "console_only",
        "note": "火山方舟可能提供模型级新客免费额度；公开 API 不返回精确剩余张数，请以控制台为准。",
        "console_url": "https://console.volcengine.com/ark",
    },
    "alibaba": {
        "kind": "shared_account_model",
        "note": "阿里云免费额度按账户/Workspace 与模型共享，并非每个 API Key 独享；剩余量需在百炼控制台查看。",
        "console_url": "https://bailian.console.aliyun.com/",
    },
}


def local_usage(session: Session, credential_id: str) -> tuple[int, float]:
    values = session.execute(
        select(
            func.coalesce(func.sum(CredentialUsage.image_count), 0),
            func.coalesce(func.sum(CredentialUsage.estimated_cost_cny), 0.0),
        ).where(CredentialUsage.credential_id == credential_id)
    ).one()
    return int(values[0]), float(values[1])


async def preflight_profile(
    session: Session,
    secret_store: SecretStore,
    profile: ProviderProfile,
    *,
    transport_factory: Callable[[ProviderCredential], httpx.AsyncBaseTransport | None]
    | None = None,
) -> dict[str, object]:
    credential_results: list[dict[str, object]] = []
    checked_at = datetime.now(UTC)
    available_credentials(session, profile.id, now=checked_at)
    for credential in credentials_for_profile(session, profile.id):
        generated, cost = local_usage(session, credential.id)
        check_status = "not_checked"
        check_message = "该提供商没有公开的无付费 Key 预检接口，请到官方控制台确认。"
        should_check = (
            profile.provider == "volcengine"
            and credential.enabled
            and credential.secret_configured
            and credential.status not in {CredentialStatus.EXHAUSTED, CredentialStatus.INVALID}
        )
        if should_check:
            secret = secret_store.get(credential.id)
            if not secret:
                credential.secret_configured = False
                credential.status = CredentialStatus.INVALID
                credential.last_error_safe = "无法读取已保存密钥，请重新填写"
                check_status = "unavailable"
                check_message = credential.last_error_safe
            else:
                provider = VolcengineProvider(
                    ProviderConfig(secret, profile.base_url, profile.workspace_id),
                    transport_factory(credential) if transport_factory else None,
                )
                try:
                    await provider.preflight()
                    credential.status = CredentialStatus.ACTIVE
                    credential.cooldown_until = None
                    credential.last_checked_at = checked_at
                    credential.last_error_safe = None
                    check_status = "ok"
                    check_message = (
                        "API 地址与网络连通；该检查不生成图片，也不能证明 Key 有效、"
                        "所选模型已开通或账户仍有可用余额。"
                    )
                except ProviderError as error:
                    record_credential_failure(
                        session, credential, error.category, error.safe_message
                    )
                    check_status = "failed"
                    check_message = error.safe_message
        payload = credential_payload(credential)
        payload.update(
            {
                "local_generated_images": generated,
                "local_estimated_cost_cny": f"{cost:.2f}",
                "preflight_status": check_status,
                "preflight_message": check_message,
            }
        )
        credential_results.append(payload)
    sync_profile_summary(session, profile)
    available_count = sum(
        item["enabled"]
        and item["secret_configured"]
        and item["status"] == CredentialStatus.ACTIVE
        and (
            item["manual_remaining_images"] is None
            or int(item["manual_remaining_images"]) > 0
        )
        for item in credential_results
    )
    quota = OFFICIAL_QUOTA.get(
        profile.provider,
        {
            "kind": "unknown",
            "note": "自定义提供商的免费额度与余额需到厂商控制台确认。",
            "console_url": "",
        },
    )
    session.flush()
    return {
        "profile_id": profile.id,
        "provider": profile.provider,
        "model_id": profile.model_id,
        "checked_at": checked_at,
        "supports_non_billable_preflight": profile.provider == "volcengine",
        "available_credential_count": available_count,
        "official_quota": quota,
        "credentials": credential_results,
    }
