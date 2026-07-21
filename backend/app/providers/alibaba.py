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

GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def _content(request: GenerationRequest) -> list[dict[str, str]]:
    content: list[dict[str, str]] = []
    if request.reference_image:
        content.append({"image": request.reference_image})
    content.append({"text": request.prompt})
    return content


def build_qwen_payload(request: GenerationRequest) -> dict[str, object]:
    parameters: dict[str, object] = {
        "n": request.requested_outputs,
        "size": request.size or "2368*1728",
        "watermark": request.watermark,
        "prompt_extend": request.prompt_extend if request.prompt_extend is not None else False,
    }
    if request.seed is not None:
        parameters["seed"] = request.seed
    return {
        "model": request.model,
        "input": {"messages": [{"role": "user", "content": _content(request)}]},
        "parameters": parameters,
    }


def build_wan_payload(request: GenerationRequest) -> dict[str, object]:
    parameters: dict[str, object] = {
        "enable_sequential": False,
        "n": request.requested_outputs,
        "size": request.size or "2048*1536",
        "watermark": request.watermark,
    }
    if request.thinking_mode is not None and not request.reference_image:
        parameters["thinking_mode"] = request.thinking_mode
    return {
        "model": request.model,
        "input": {"messages": [{"role": "user", "content": _content(request)}]},
        "parameters": parameters,
    }


def parse_alibaba_response(body: dict[str, object]) -> GenerationResult:
    output = body.get("output")
    images: list[ImageSource] = []
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        value = item.get("image") or item.get("image_url") or item.get("url")
                        if isinstance(value, str):
                            images.append(ImageSource(url=value))
        results = output.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    images.append(ImageSource(url=item["url"]))
    if not images:
        raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "服务未返回可用图片")
    request_id = body.get("request_id")
    usage = body.get("usage")
    return GenerationResult(
        images=tuple(images),
        provider_request_id=request_id if isinstance(request_id, str) else None,
        usage=usage if isinstance(usage, dict) else {},
    )


class AlibabaProvider:
    def __init__(self, config: ProviderConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        payload = (
            build_qwen_payload(request)
            if request.model.startswith("qwen-image")
            else build_wan_payload(request)
        )
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if self.config.workspace_id:
            headers["X-DashScope-WorkSpace"] = self.config.workspace_id
        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(600, connect=20),
                transport=self.transport,
            ) as client:
                response = await client.post(GENERATION_PATH, json=payload)
                response.raise_for_status()
                return parse_alibaba_response(response.json())
        except httpx.HTTPStatusError as error:
            raise classify_vendor_http_error(error, "alibaba") from error
        except httpx.TimeoutException as error:
            raise ProviderError(ProviderErrorCategory.TIMEOUT, "生图请求超时") from error
        except (ValueError, TypeError) as error:
            raise ProviderError(
                ProviderErrorCategory.MALFORMED_RESPONSE, "服务返回内容无法解析"
            ) from error
