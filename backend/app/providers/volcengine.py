from __future__ import annotations

import httpx

from app.providers.base import (
    GenerationRequest,
    GenerationResult,
    ImageSource,
    ProviderConfig,
)
from app.providers.errors import (
    ProviderError,
    ProviderErrorCategory,
    classify_vendor_http_error,
)


SEEDREAM_GENERATION_PATHS = {
    "standard": "/api/v3/images/generations",
    "agent_plan": "/api/plan/v3/images/generations",
}


def seedream_generation_path(api_mode: str) -> str:
    return SEEDREAM_GENERATION_PATHS.get(api_mode, SEEDREAM_GENERATION_PATHS["standard"])


def build_seedream_payload(request: GenerationRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": request.model,
        "prompt": request.prompt,
        "response_format": "b64_json",
        "size": request.size or "2048x2048",
        "watermark": request.watermark,
    }
    if request.reference_image:
        payload["image"] = request.reference_image
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.guidance_scale is not None:
        payload["guidance_scale"] = request.guidance_scale
    if request.requested_outputs == 1:
        payload["sequential_image_generation"] = "disabled"
    else:
        payload["sequential_image_generation"] = "auto"
        payload["sequential_image_generation_options"] = {
            "max_images": request.requested_outputs
        }
    return payload


def parse_seedream_response(body: dict[str, object]) -> GenerationResult:
    raw_items = body.get("data")
    if not isinstance(raw_items, list):
        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "服务未返回可用图片")
    images: list[ImageSource] = []
    for item in raw_items:
        if isinstance(item, dict):
            url = item.get("url")
            b64_json = item.get("b64_json")
            if isinstance(url, str) or isinstance(b64_json, str):
                images.append(
                    ImageSource(
                        url=url if isinstance(url, str) else None,
                        b64_json=b64_json if isinstance(b64_json, str) else None,
                    )
                )
    if not images:
        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "服务未返回可用图片")
    request_id = body.get("request_id")
    usage = body.get("usage")
    return GenerationResult(
        images=tuple(images),
        provider_request_id=request_id if isinstance(request_id, str) else None,
        usage=usage if isinstance(usage, dict) else {},
    )


class VolcengineProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        timeout = httpx.Timeout(600, connect=20)
        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    seedream_generation_path(self.config.api_mode),
                    json=build_seedream_payload(request),
                )
                response.raise_for_status()
                return parse_seedream_response(response.json())
        except httpx.HTTPStatusError as error:
            raise classify_vendor_http_error(error, "volcengine") from error
        except httpx.TimeoutException as error:
            raise ProviderError(ProviderErrorCategory.TIMEOUT, "生图请求超时") from error
        except (ValueError, TypeError) as error:
            raise ProviderError(
                ProviderErrorCategory.MALFORMED_RESPONSE, "服务返回内容无法解析"
            ) from error

    async def preflight(self) -> None:
        """Validate credentials with the documented non-billable root ping."""
        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=httpx.Timeout(20, connect=10),
                transport=self.transport,
            ) as client:
                response = await client.get("/ping")
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise classify_vendor_http_error(error, "volcengine") from error
        except httpx.TimeoutException as error:
            raise ProviderError(ProviderErrorCategory.TIMEOUT, "火山方舟连通性检查超时") from error
