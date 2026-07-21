from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CredentialUsage, GenerationTask, ProviderCredential, ProviderProfile
from app.domain.enums import CredentialStatus
from app.domain.errors import InvalidStateTransitionError
from app.providers.errors import ProviderErrorCategory
from app.security.secrets import SecretStore


def credentials_for_profile(session: Session, profile_id: str) -> list[ProviderCredential]:
    return list(
        session.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.profile_id == profile_id)
            .order_by(ProviderCredential.priority, ProviderCredential.created_at)
        ).all()
    )


def available_credentials(
    session: Session, profile_id: str, *, now: datetime | None = None
) -> list[ProviderCredential]:
    checked_at = now or datetime.now(UTC)
    available: list[ProviderCredential] = []
    for credential in credentials_for_profile(session, profile_id):
        if not credential.enabled or not credential.secret_configured:
            continue
        if credential.manual_remaining_images is not None and credential.manual_remaining_images <= 0:
            continue
        if credential.status in {CredentialStatus.EXHAUSTED, CredentialStatus.INVALID}:
            continue
        if credential.status == CredentialStatus.COOLDOWN:
            cooldown = credential.cooldown_until
            if cooldown is not None and cooldown.tzinfo is None:
                cooldown = cooldown.replace(tzinfo=UTC)
            if cooldown is not None and cooldown > checked_at:
                continue
            credential.status = CredentialStatus.ACTIVE
            credential.cooldown_until = None
        available.append(credential)
    session.flush()
    return available


def acquire_credential(
    session: Session,
    secret_store: SecretStore,
    profile: ProviderProfile,
) -> tuple[ProviderCredential, str] | None:
    """Return the first usable key without ever crossing profile boundaries."""
    for credential in available_credentials(session, profile.id):
        secret = secret_store.get(credential.id)
        if secret:
            credential.last_checked_at = datetime.now(UTC)
            session.flush()
            return credential, secret
        credential.secret_configured = False
        credential.status = CredentialStatus.INVALID
        credential.last_error_safe = "密钥未能从 Windows 凭据管理器或当前会话中读取"
    sync_profile_summary(session, profile)
    return None


def record_credential_success(
    session: Session,
    credential: ProviderCredential,
    task: GenerationTask,
    image_count: int,
    unit_price_cny: float | None,
) -> None:
    credential.last_used_at = datetime.now(UTC)
    credential.last_checked_at = credential.last_used_at
    credential.failure_count = 0
    credential.last_error_safe = None
    credential.status = CredentialStatus.ACTIVE
    if credential.manual_remaining_images is not None:
        credential.manual_remaining_images = max(
            0, credential.manual_remaining_images - image_count
        )
        if credential.manual_remaining_images == 0:
            credential.status = CredentialStatus.EXHAUSTED
    session.add(
        CredentialUsage(
            credential_id=credential.id,
            task_id=task.id,
            provider=session.get(ProviderProfile, credential.profile_id).provider,
            model=task.model_id,
            image_count=image_count,
            estimated_cost_cny=(
                unit_price_cny * image_count if unit_price_cny is not None else None
            ),
        )
    )
    session.flush()


def record_credential_failure(
    session: Session,
    credential: ProviderCredential,
    category: ProviderErrorCategory | str,
    safe_message: str,
    *,
    cooldown_seconds: float | None = None,
) -> None:
    now = datetime.now(UTC)
    credential.failure_count += 1
    credential.last_checked_at = now
    credential.last_error_safe = safe_message[:500]
    if category == ProviderErrorCategory.AUTHENTICATION:
        credential.status = CredentialStatus.INVALID
    elif category == ProviderErrorCategory.QUOTA:
        credential.status = CredentialStatus.EXHAUSTED
        credential.manual_remaining_images = 0
    elif category == ProviderErrorCategory.RATE_LIMIT:
        credential.status = CredentialStatus.COOLDOWN
        credential.cooldown_until = now.replace(microsecond=0) + timedelta(
            seconds=max(1, cooldown_seconds or 60)
        )
    elif category in {ProviderErrorCategory.TIMEOUT, ProviderErrorCategory.TRANSIENT}:
        credential.status = CredentialStatus.COOLDOWN
        credential.cooldown_until = now.replace(microsecond=0) + timedelta(seconds=30)
    session.flush()


def sync_profile_summary(session: Session, profile: ProviderProfile) -> None:
    configured = [item for item in credentials_for_profile(session, profile.id) if item.secret_configured]
    profile.secret_configured = bool(configured)
    profile.last_four = configured[0].last_four if configured else None
    profile.remember_secret = any(item.remember_secret for item in configured)
    session.flush()


def save_credential(
    session: Session,
    secret_store: SecretStore,
    profile: ProviderProfile,
    *,
    credential_id: str | None,
    label: str,
    account_label: str = "",
    priority: int = 100,
    api_key: str | None = None,
    remember_secret: bool = False,
    enabled: bool = True,
    manual_remaining_images: int | None = None,
) -> tuple[ProviderCredential, bool]:
    credential = session.get(ProviderCredential, credential_id) if credential_id else None
    if credential is not None and credential.profile_id != profile.id:
        raise InvalidStateTransitionError("不能编辑其他提供商配置的密钥")
    if credential is None:
        credential = session.scalar(
            select(ProviderCredential).where(
                ProviderCredential.profile_id == profile.id,
                ProviderCredential.label == label.strip(),
            )
        )
    if credential is None:
        if not api_key:
            raise InvalidStateTransitionError("新增密钥时必须填写 API Key")
        credential = ProviderCredential(profile_id=profile.id, label=label.strip() or "API Key")
        session.add(credential)
        session.flush()
    credential.label = label.strip() or credential.label
    credential.account_label = account_label.strip()
    credential.priority = priority
    credential.enabled = enabled
    credential.remember_secret = remember_secret
    credential.manual_remaining_images = manual_remaining_images
    session_only = False
    if api_key:
        remembered = secret_store.set(credential.id, api_key, remember_secret)
        credential.secret_configured = True
        credential.last_four = api_key[-4:]
        credential.status = CredentialStatus.ACTIVE
        credential.last_error_safe = None
        session_only = not remembered
    elif not enabled:
        credential.status = CredentialStatus.DISABLED
    elif credential.status == CredentialStatus.DISABLED:
        credential.status = CredentialStatus.ACTIVE
    if enabled and credential.secret_configured:
        if manual_remaining_images == 0:
            credential.status = CredentialStatus.EXHAUSTED
        elif (
            manual_remaining_images is not None
            and manual_remaining_images > 0
            and credential.status == CredentialStatus.EXHAUSTED
        ):
            credential.status = CredentialStatus.ACTIVE
    sync_profile_summary(session, profile)
    return credential, session_only


def disable_credential(
    session: Session,
    secret_store: SecretStore,
    profile: ProviderProfile,
    credential_id: str,
) -> None:
    credential = session.get(ProviderCredential, credential_id)
    if credential is None or credential.profile_id != profile.id:
        raise InvalidStateTransitionError("密钥不存在")
    secret_store.clear(credential.id)
    credential.secret_configured = False
    credential.enabled = False
    credential.status = CredentialStatus.DISABLED
    credential.last_four = None
    sync_profile_summary(session, profile)


def migrate_legacy_credentials(session: Session, secret_store: SecretStore) -> None:
    profiles = session.scalars(select(ProviderProfile)).all()
    for profile in profiles:
        if credentials_for_profile(session, profile.id) or not profile.secret_configured:
            continue
        legacy_secret = secret_store.get(profile.id)
        credential = ProviderCredential(
            profile_id=profile.id,
            label="原主 Key",
            priority=10,
            enabled=True,
            secret_configured=legacy_secret is not None,
            last_four=profile.last_four,
            remember_secret=profile.remember_secret,
            status=(CredentialStatus.ACTIVE if legacy_secret else CredentialStatus.INVALID),
            last_error_safe=None if legacy_secret else "原密钥仅保存在上次运行内存中，请重新填写",
        )
        session.add(credential)
        session.flush()
        if legacy_secret:
            secret_store.set(credential.id, legacy_secret, profile.remember_secret)
            secret_store.clear(profile.id)
        sync_profile_summary(session, profile)


def reconcile_persisted_credentials(session: Session, secret_store: SecretStore) -> None:
    """Make database status match secrets actually readable in this process."""
    credentials = session.scalars(select(ProviderCredential)).all()
    affected_profiles: set[str] = set()
    for credential in credentials:
        if not credential.secret_configured:
            continue
        if secret_store.get(credential.id):
            continue
        credential.secret_configured = False
        credential.status = CredentialStatus.INVALID
        credential.last_error_safe = "已保存的密钥无法读取；若原先仅本次运行有效，请重新填写"
        affected_profiles.add(credential.profile_id)
    for profile_id in affected_profiles:
        profile = session.get(ProviderProfile, profile_id)
        if profile:
            sync_profile_summary(session, profile)
    session.flush()


def credential_payload(credential: ProviderCredential, *, session_only: bool = False) -> dict[str, object]:
    return {
        "id": credential.id,
        "profile_id": credential.profile_id,
        "label": credential.label,
        "account_label": credential.account_label,
        "priority": credential.priority,
        "enabled": credential.enabled,
        "secret_configured": credential.secret_configured,
        "last_four": credential.last_four,
        "remember_secret": credential.remember_secret,
        "status": credential.status,
        "manual_remaining_images": credential.manual_remaining_images,
        "cooldown_until": credential.cooldown_until,
        "last_checked_at": credential.last_checked_at,
        "last_used_at": credential.last_used_at,
        "failure_count": credential.failure_count,
        "last_error_safe": credential.last_error_safe,
        "session_only": session_only,
    }
