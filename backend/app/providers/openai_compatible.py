from __future__ import annotations

import httpx

from app.providers.base import GenerationRequest, GenerationResult, ImageSource, ProviderConfig
from app.providers.errors import ProviderError, ProviderErrorCategory, classify_http_error


class OpenAICompatibleProvider:
    """Configurable JSON image endpoint for vendors using OpenAI-style generation APIs."""

    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        payload: dict[str, object] = {
            "model": request.model,
            "prompt": request.prompt,
            "n": request.requested_outputs,
            "response_format": "b64_json",
        }
        if request.size:
            payload["size"] = request.size
        if request.reference_image:
            payload["image"] = request.reference_image
        try:
            async with httpx.AsyncClient(
                base_url=f"{self.config.base_url.rstrip('/')}/",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=httpx.Timeout(600, connect=20),
                transport=self.transport,
            ) as client:
                response = await client.post("images/generations", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as error:
            raise classify_http_error(error) from error
        except httpx.TimeoutException as error:
            raise ProviderError(ProviderErrorCategory.TIMEOUT, "生图请求超时") from error
        raw_images = body.get("data") if isinstance(body, dict) else None
        images: list[ImageSource] = []
        if isinstance(raw_images, list):
            for item in raw_images:
                if not isinstance(item, dict):
                    continue
                url, b64 = item.get("url"), item.get("b64_json")
                if isinstance(url, str) or isinstance(b64, str):
                    images.append(
                        ImageSource(
                            url=url if isinstance(url, str) else None,
                            b64_json=b64 if isinstance(b64, str) else None,
                        )
                    )
        if not images:
            raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "服务未返回可用图片")
        return GenerationResult(images=tuple(images))
