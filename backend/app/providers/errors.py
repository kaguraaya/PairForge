from enum import StrEnum
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
import math
import re

import httpx


class ProviderErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SAFETY = "safety"
    INVALID_REQUEST = "invalid_request"
    TRANSIENT = "transient"
    MALFORMED_RESPONSE = "malformed_response"


class ProviderError(RuntimeError):
    def __init__(
        self,
        category: ProviderErrorCategory,
        safe_message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.category = category
        self.safe_message = safe_message
        self.retry_after_seconds = retry_after_seconds
        super().__init__(safe_message)


_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9._:-]")


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = (retry_at - (now or datetime.now(UTC))).total_seconds()
    if not math.isfinite(seconds):
        return None
    return float(max(1, min(math.ceil(seconds), 3600)))


def _safe_identifier(value: object, maximum: int = 120) -> str:
    if not isinstance(value, str):
        return ""
    return _SAFE_IDENTIFIER.sub("", value)[:maximum]


def _error_identifiers(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    nested_error = payload.get("error")
    raw_code = payload.get("code")
    request_id = payload.get("request_id") or payload.get("requestId")
    if isinstance(nested_error, dict):
        raw_code = raw_code or nested_error.get("code")
        request_id = request_id or nested_error.get("request_id")
    return _safe_identifier(raw_code), _safe_identifier(request_id)


def _with_identifiers(message: str, code: str, request_id: str, http_status: int) -> str:
    details = [f"HTTP {http_status}"]
    if code:
        details.append(f"厂商错误码：{code}")
    if request_id:
        details.append(f"请求 ID：{request_id}")
    return f"{message}（{'；'.join(details)}）" if details else message


def classify_http_error(error: httpx.HTTPStatusError) -> ProviderError:
    status = error.response.status_code
    if status in {401, 403}:
        return ProviderError(ProviderErrorCategory.AUTHENTICATION, "API 密钥或权限无效")
    if status == 429:
        return ProviderError(
            ProviderErrorCategory.RATE_LIMIT,
            "请求过于频繁，请稍后重试",
            retry_after_seconds=parse_retry_after(error.response.headers.get("Retry-After")),
        )
    if status in {402, 409}:
        return ProviderError(ProviderErrorCategory.QUOTA, "服务额度不足或账户不可用")
    if status in {400, 404, 422}:
        return ProviderError(ProviderErrorCategory.INVALID_REQUEST, "模型或请求参数无效")
    if status >= 500:
        return ProviderError(ProviderErrorCategory.TRANSIENT, "生图服务暂时不可用")
    return ProviderError(ProviderErrorCategory.INVALID_REQUEST, "生图服务拒绝了请求")


def classify_vendor_http_error(
    error: httpx.HTTPStatusError, provider: str
) -> ProviderError:
    """Classify documented vendor codes without exposing response bodies."""
    try:
        payload = error.response.json()
    except ValueError:
        payload = {}
    raw_code, request_id = _error_identifiers(payload)
    code = raw_code.lower()

    retry_after = parse_retry_after(error.response.headers.get("Retry-After"))

    def vendor_error(category: ProviderErrorCategory, message: str) -> ProviderError:
        return ProviderError(
            category,
            _with_identifiers(message, raw_code, request_id, error.response.status_code),
            retry_after_seconds=(retry_after if category == ProviderErrorCategory.RATE_LIMIT else None),
        )

    if provider == "alibaba":
        if any(marker in code for marker in ("invalidapikey", "accessdenied", "unauthorized")):
            return vendor_error(ProviderErrorCategory.AUTHENTICATION, "阿里云 API Key 或权限无效")
        if any(marker in code for marker in ("allocationquota", "arrearage", "quotaexceeded")):
            return vendor_error(ProviderErrorCategory.QUOTA, "阿里云账户额度不足或免费额度已用完")
        if "throttl" in code or "ratelimit" in code:
            return vendor_error(ProviderErrorCategory.RATE_LIMIT, "阿里云请求频率受限")
        if any(marker in code for marker in ("datainspection", "inappropriate", "safety")):
            return vendor_error(ProviderErrorCategory.SAFETY, "请求或图片未通过内容安全检查")
    if provider == "volcengine":
        if any(marker in code for marker in ("accessdenied", "unauthorized", "invalidapikey")):
            return vendor_error(ProviderErrorCategory.AUTHENTICATION, "火山方舟 API Key 或权限无效")
        if any(marker in code for marker in ("accountoverdue", "quotaexceeded", "insufficient")):
            return vendor_error(ProviderErrorCategory.QUOTA, "火山方舟账户余额或额度不足")
        if "ratelimit" in code or "throttl" in code:
            return vendor_error(ProviderErrorCategory.RATE_LIMIT, "火山方舟请求频率受限")
        if any(marker in code for marker in ("safety", "contentfilter", "sensitivecontent")):
            return vendor_error(ProviderErrorCategory.SAFETY, "提示词或生成结果未通过内容安全检查")
        if any(marker in code for marker in (
            "invalidendpointormodel.notfound", "modelnotfound", "endpointnotfound", "model_not_found"
        )):
            return vendor_error(
                ProviderErrorCategory.INVALID_REQUEST,
                "当前账号未开通所选模型，或模型 ID/推理接入点不存在；请先到火山方舟控制台开通该模型",
            )
        if "size" in code or "resolution" in code:
            return vendor_error(
                ProviderErrorCategory.INVALID_REQUEST,
                "图片尺寸或比例不符合当前模型要求，请改用该模型的尺寸预设",
            )
        if "invalidparameter" in code:
            return vendor_error(
                ProviderErrorCategory.INVALID_REQUEST,
                "请求参数不符合当前模型要求，请检查模型、尺寸和模型专属设置",
            )
    fallback = classify_http_error(error)
    return vendor_error(fallback.category, fallback.safe_message)
