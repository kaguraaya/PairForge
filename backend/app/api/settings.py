from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Project, ProviderProfile
from app.domain.errors import DomainError
from app.providers.registry import model_registry
from app.providers.size_rules import (
    normalize_generation_config,
    seedream_5_lite_size_error,
)
from app.services.credentials import (
    credential_payload,
    credentials_for_profile,
    disable_credential,
    save_credential,
    sync_profile_summary,
)
from app.services.quota_status import local_usage

router = APIRouter(prefix="/api/settings", tags=["settings"])
SECRET_CONFIG_KEYS = {"api_key", "apikey", "secret", "token", "authorization", "password"}


class ProfileInput(BaseModel):
    id: str | None = None
    project_id: str | None = None
    provider: str
    display_name: str
    base_url: str
    region: str | None = None
    workspace_id: str | None = None
    model_id: str
    api_key: str | None = None
    remember_secret: bool = False
    config: dict[str, object] = Field(default_factory=dict)


class CredentialInput(BaseModel):
    id: str | None = None
    label: str = Field(min_length=1, max_length=120)
    account_label: str = Field(default="", max_length=120)
    priority: int = Field(default=100, ge=1, le=10_000)
    api_key: str | None = None
    remember_secret: bool = False
    enabled: bool = True
    manual_remaining_images: int | None = Field(default=None, ge=0)


def config_contains_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower().replace("-", "_") in SECRET_CONFIG_KEYS:
                return True
            if config_contains_secret(nested):
                return True
    if isinstance(value, list):
        return any(config_contains_secret(item) for item in value)
    return False


def validate_generation_config(
    config: dict[str, object], provider: str = "", model_id: str = ""
) -> None:
    size = config.get("size")
    if size is not None and (not isinstance(size, str) or not 1 <= len(size) <= 64):
        raise HTTPException(400, "输出尺寸格式无效")
    if isinstance(size, str):
        size_error = seedream_5_lite_size_error(provider, model_id, size)
        if size_error:
            raise HTTPException(400, size_error)
    for key in ("watermark", "prompt_extend", "thinking_mode", "single_output_default"):
        if key in config and not isinstance(config[key], bool):
            raise HTTPException(400, f"{key} 必须是布尔值")
    for key in ("default_q1_outputs", "default_q2_outputs"):
        value = config.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 15
        ):
            raise HTTPException(400, f"{key} 必须是 1 到 15 之间的整数")
    seed = config.get("seed")
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2_147_483_647
    ):
        raise HTTPException(400, "seed 必须是 0 到 2147483647 之间的整数")
    guidance = config.get("guidance_scale")
    if guidance is not None and (
        isinstance(guidance, bool)
        or not isinstance(guidance, (int, float))
        or not 1 <= float(guidance) <= 10
    ):
        raise HTTPException(400, "guidance_scale 必须在 1 到 10 之间")


def is_official_host(provider: str, hostname: str) -> bool:
    if provider == "volcengine":
        return hostname == "ark.cn-beijing.volces.com"
    if provider != "alibaba":
        return True
    if hostname in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}:
        return True
    labels = hostname.split(".")
    return (
        len(labels) == 5
        and bool(labels[0])
        and labels[1] in {"cn-beijing", "ap-southeast-1"}
        and labels[2:] == ["maas", "aliyuncs", "com"]
    )


@router.get("/models")
def list_models() -> list[dict[str, object]]:
    provider_links = {
        "volcengine": {
            "api_key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apikey",
            "provider_console_url": "https://console.volcengine.com/ark",
        },
        "alibaba": {
            "api_key_url": "https://help.aliyun.com/zh/model-studio/get-api-key",
            "provider_console_url": "https://bailian.console.aliyun.com/",
        },
    }
    return [
        {
            "provider": item.provider,
            "model": item.model,
            "display_name": item.display_name,
            "supports_text_to_image": item.supports_text_to_image,
            "supports_image_edit": item.supports_image_edit,
            "max_text_outputs": item.max_text_outputs,
            "max_edit_outputs": item.max_edit_outputs,
            "default_size": item.default_size,
            "multiple_output_semantics": item.multiple_output_semantics,
            "unit_price_cny": str(item.unit_price_cny),
            "price_checked_on": item.price_checked_on,
            "documentation_url": item.documentation_url,
            **provider_links.get(item.provider, {}),
        }
        for item in model_registry.list()
    ]


def profile_payload(
    profile: ProviderProfile, session: Session, session_only: bool = False
) -> dict[str, object]:
    credentials = []
    for item in credentials_for_profile(session, profile.id):
        generated, cost = local_usage(session, item.id)
        payload = credential_payload(item)
        payload.update(
            {
                "local_generated_images": generated,
                "local_estimated_cost_cny": f"{cost:.2f}",
            }
        )
        credentials.append(payload)
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "provider": profile.provider,
        "display_name": profile.display_name,
        "base_url": profile.base_url,
        "region": profile.region,
        "workspace_id": profile.workspace_id,
        "model_id": profile.model_id,
        "secret_configured": profile.secret_configured,
        "last_four": profile.last_four,
        "remember_secret": profile.remember_secret,
        "session_only": session_only,
        "config": normalize_generation_config(
            profile.provider, profile.model_id, profile.config
        ),
        "credentials": credentials,
    }


@router.get("/profiles")
def list_profiles(
    project_id: str | None = None, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    query = select(ProviderProfile)
    if project_id:
        query = query.where(ProviderProfile.project_id == project_id)
    return [profile_payload(item, session) for item in session.scalars(query).all()]


@router.post("/profiles")
def save_profile(
    body: ProfileInput,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if config_contains_secret(body.config):
        raise HTTPException(400, "扩展配置中不能保存密钥、令牌或密码")
    normalized_config = normalize_generation_config(
        body.provider, body.model_id, body.config
    )
    validate_generation_config(normalized_config, body.provider, body.model_id)
    parsed_url = urlparse(body.base_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise HTTPException(400, "API 地址必须是有效的 HTTPS 地址")
    if not is_official_host(body.provider, parsed_url.hostname):
        raise HTTPException(400, "内置提供商只能使用其官方 API 域名；其他地址请使用自定义服务")
    profile = session.get(ProviderProfile, body.id) if body.id else None
    if profile is None:
        profile = ProviderProfile(
            project_id=body.project_id,
            provider=body.provider,
            display_name=body.display_name,
            base_url=body.base_url,
            model_id=body.model_id,
        )
        session.add(profile)
        session.flush()
    profile.provider = body.provider
    profile.display_name = body.display_name
    profile.base_url = body.base_url.rstrip("/")
    profile.region = body.region
    profile.workspace_id = body.workspace_id
    profile.model_id = body.model_id
    profile.remember_secret = body.remember_secret
    profile.config = normalized_config
    session_only = False
    if body.api_key:
        _credential, session_only = save_credential(
            session,
            request.app.state.secret_store,
            profile,
            credential_id=None,
            label="主 Key",
            priority=10,
            api_key=body.api_key,
            remember_secret=body.remember_secret,
        )
    else:
        sync_profile_summary(session, profile)
    if body.project_id:
        project = session.get(Project, body.project_id)
        if project:
            project.selected_provider_profile_id = profile.id
    session.commit()
    return profile_payload(profile, session, session_only)


@router.get("/profiles/{profile_id}/credentials")
def list_credentials(
    profile_id: str, session: Session = Depends(get_session)
) -> list[dict[str, object]]:
    if not session.get(ProviderProfile, profile_id):
        raise HTTPException(404, "服务配置不存在")
    return [credential_payload(item) for item in credentials_for_profile(session, profile_id)]


@router.post("/profiles/{profile_id}/credentials")
def upsert_credential(
    profile_id: str,
    body: CredentialInput,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    profile = session.get(ProviderProfile, profile_id)
    if not profile:
        raise HTTPException(404, "服务配置不存在")
    try:
        credential, session_only = save_credential(
            session,
            request.app.state.secret_store,
            profile,
            credential_id=body.id,
            label=body.label,
            account_label=body.account_label,
            priority=body.priority,
            api_key=body.api_key,
            remember_secret=body.remember_secret,
            enabled=body.enabled,
            manual_remaining_images=body.manual_remaining_images,
        )
    except DomainError as error:
        raise HTTPException(409, str(error)) from error
    session.commit()
    return credential_payload(credential, session_only=session_only)


@router.delete("/profiles/{profile_id}/credentials/{credential_id}")
def delete_credential(
    profile_id: str,
    credential_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    profile = session.get(ProviderProfile, profile_id)
    if not profile:
        raise HTTPException(404, "服务配置不存在")
    try:
        disable_credential(
            session, request.app.state.secret_store, profile, credential_id
        )
    except DomainError as error:
        raise HTTPException(404, str(error)) from error
    session.commit()
    return {"disabled": True}


@router.delete("/profiles/{profile_id}/secret")
def clear_profile_secret(
    profile_id: str, request: Request, session: Session = Depends(get_session)
) -> dict[str, bool]:
    profile = session.get(ProviderProfile, profile_id)
    if not profile:
        raise HTTPException(404, "服务配置不存在")
    for credential in credentials_for_profile(session, profile.id):
        disable_credential(session, request.app.state.secret_store, profile, credential.id)
    session.commit()
    return {"cleared": True}
