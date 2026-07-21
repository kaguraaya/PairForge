import httpx
import pytest

from app.domain.enums import GenerationStage
from app.providers.alibaba import AlibabaProvider, build_qwen_payload, build_wan_payload
from app.providers.base import GenerationRequest, ProviderConfig
from app.providers.errors import (
    ProviderErrorCategory,
    classify_vendor_http_error,
    parse_retry_after,
)
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.volcengine import VolcengineProvider, build_seedream_payload


def request(
    model: str,
    outputs: int = 1,
    reference: str | None = None,
    **options,
) -> GenerationRequest:
    return GenerationRequest(
        model=model,
        prompt="当前题目提示词",
        stage=GenerationStage.IMAGE2 if reference else GenerationStage.IMAGE1,
        requested_outputs=outputs,
        reference_image=reference,
        **options,
    )


def test_seedream_single_and_candidate_payloads() -> None:
    single = build_seedream_payload(request("doubao-seedream-5-0-lite-260128"))
    multiple = build_seedream_payload(request("doubao-seedream-5-0-lite-260128", 3))
    assert single["sequential_image_generation"] == "disabled"
    assert "sequential_image_generation_options" not in single
    assert multiple["sequential_image_generation"] == "auto"
    assert multiple["sequential_image_generation_options"] == {"max_images": 3}


def test_qwen_and_wan_do_not_share_parameters() -> None:
    qwen = build_qwen_payload(request("qwen-image-2.0", reference="data:image/png;base64,AAA"))
    wan = build_wan_payload(request("wan2.7-image"))
    assert qwen["parameters"] == {
        "n": 1,
        "size": "2368*1728",
        "watermark": False,
        "prompt_extend": False,
    }
    assert wan["parameters"] == {
        "enable_sequential": False,
        "n": 1,
        "size": "2048*1536",
        "watermark": False,
    }
    content = qwen["input"]["messages"][0]["content"]
    assert content == [
        {"image": "data:image/png;base64,AAA"},
        {"text": "当前题目提示词"},
    ]


def test_advanced_parameters_are_mapped_only_to_supported_vendor_fields() -> None:
    seedream = build_seedream_payload(
        request(
            "doubao-seedream-5-0-lite-260128",
            seed=42,
            guidance_scale=6.5,
            watermark=True,
            prompt_extend=True,
            thinking_mode=False,
        )
    )
    assert seedream["seed"] == 42
    assert seedream["guidance_scale"] == 6.5
    assert seedream["watermark"] is True
    assert "prompt_extend" not in seedream
    assert "thinking_mode" not in seedream

    qwen = build_qwen_payload(
        request(
            "qwen-image-2.0",
            seed=73,
            prompt_extend=True,
            guidance_scale=4.0,
            thinking_mode=False,
        )
    )
    assert qwen["parameters"]["seed"] == 73
    assert qwen["parameters"]["prompt_extend"] is True
    assert "guidance_scale" not in qwen["parameters"]
    assert "thinking_mode" not in qwen["parameters"]

    wan_text = build_wan_payload(
        request("wan2.7-image", thinking_mode=False, seed=99, prompt_extend=True)
    )
    assert wan_text["parameters"]["thinking_mode"] is False
    assert "seed" not in wan_text["parameters"]
    assert "prompt_extend" not in wan_text["parameters"]

    wan_edit = build_wan_payload(
        request(
            "wan2.7-image",
            reference="data:image/png;base64,AAA",
            thinking_mode=True,
        )
    )
    assert "thinking_mode" not in wan_edit["parameters"]


@pytest.mark.asyncio
async def test_adapters_parse_normalized_images_without_real_network() -> None:
    async def seedream_handler(request_: httpx.Request) -> httpx.Response:
        assert request_.url.path == "/api/v3/images/generations"
        return httpx.Response(200, json={"data": [{"b64_json": "AAA"}], "request_id": "r1"})

    async def alibaba_handler(request_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {"choices": [{"message": {"content": [{"image": "https://x"}]}}]},
                "request_id": "r2",
            },
        )

    volc = VolcengineProvider(
        ProviderConfig("secret", "https://ark.cn-beijing.volces.com"),
        httpx.MockTransport(seedream_handler),
    )
    ali = AlibabaProvider(
        ProviderConfig("secret", "https://dashscope.aliyuncs.com"),
        httpx.MockTransport(alibaba_handler),
    )
    assert (await volc.generate(request("doubao-seedream-5-0-lite-260128"))).images[0].b64_json
    assert (await ali.generate(request("qwen-image-2.0"))).images[0].url == "https://x"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_mode", "expected_path"),
    [
        ("standard", "/api/v3/images/generations"),
        ("agent_plan", "/api/plan/v3/images/generations"),
    ],
)
async def test_volcengine_uses_selected_billing_channel(
    api_mode: str, expected_path: str
) -> None:
    async def handler(request_: httpx.Request) -> httpx.Response:
        assert request_.url.path == expected_path
        return httpx.Response(200, json={"data": [{"b64_json": "AAA"}]})

    provider = VolcengineProvider(
        ProviderConfig(
            "secret",
            "https://ark.cn-beijing.volces.com",
            api_mode=api_mode,
        ),
        httpx.MockTransport(handler),
    )
    await provider.generate(request("doubao-seedream-5-0-lite-260128"))


@pytest.mark.asyncio
async def test_custom_openai_compatible_provider_preserves_base_path_prefix() -> None:
    async def handler(request_: httpx.Request) -> httpx.Response:
        assert request_.url == httpx.URL("https://images.example/v1/images/generations")
        return httpx.Response(200, json={"data": [{"b64_json": "AAA"}]})

    provider = OpenAICompatibleProvider(
        ProviderConfig("secret", "https://images.example/v1"),
        httpx.MockTransport(handler),
    )
    result = await provider.generate(request("other-image-model"))
    assert result.images[0].b64_json == "AAA"


@pytest.mark.asyncio
async def test_volcengine_preflight_uses_non_billable_root_ping() -> None:
    async def handler(request_: httpx.Request) -> httpx.Response:
        assert request_.url.path == "/ping"
        assert request_.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, text="pong")

    provider = VolcengineProvider(
        ProviderConfig("secret", "https://ark.cn-beijing.volces.com"),
        httpx.MockTransport(handler),
    )
    await provider.preflight()


def test_documented_alibaba_quota_code_is_not_misclassified_as_bad_parameters() -> None:
    request_ = httpx.Request("POST", "https://dashscope.aliyuncs.com/api")
    response = httpx.Response(
        400,
        request=request_,
        json={"code": "AllocationQuota.FreeTierOnly", "message": "sensitive detail"},
    )
    error = classify_vendor_http_error(
        httpx.HTTPStatusError("bad", request=request_, response=response), "alibaba"
    )
    assert error.category == ProviderErrorCategory.QUOTA
    assert "sensitive detail" not in error.safe_message
    assert "AllocationQuota.FreeTierOnly" in error.safe_message


def test_rate_limit_preserves_retry_after_for_scheduler() -> None:
    request_ = httpx.Request("POST", "https://dashscope.aliyuncs.com/api")
    response = httpx.Response(
        429,
        request=request_,
        headers={"Retry-After": "37"},
        json={"code": "Throttling.RateQuota"},
    )
    error = classify_vendor_http_error(
        httpx.HTTPStatusError("limited", request=request_, response=response), "alibaba"
    )
    assert error.category == ProviderErrorCategory.RATE_LIMIT
    assert error.retry_after_seconds == 37


def test_retry_after_rejects_invalid_values_and_caps_long_waits() -> None:
    assert parse_retry_after("not-a-date") is None
    assert parse_retry_after("99999") == 3600


@pytest.mark.parametrize(
    ("code", "category", "expected"),
    [
        (
            "InvalidEndpointOrModel.NotFound",
            ProviderErrorCategory.INVALID_REQUEST,
            "未开通所选模型",
        ),
        (
            "InputTextSensitiveContentDetected",
            ProviderErrorCategory.SAFETY,
            "内容安全",
        ),
        (
            "InvalidParameter.Size",
            ProviderErrorCategory.INVALID_REQUEST,
            "尺寸",
        ),
    ],
)
def test_volcengine_errors_keep_safe_vendor_code_and_actionable_reason(
    code: str, category: ProviderErrorCategory, expected: str
) -> None:
    request_ = httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations")
    response = httpx.Response(
        400,
        request=request_,
        json={"code": code, "message": "prompt and secret must not leak", "request_id": "req-safe-1"},
    )
    error = classify_vendor_http_error(
        httpx.HTTPStatusError("bad", request=request_, response=response), "volcengine"
    )
    assert error.category == category
    assert "HTTP 400" in error.safe_message
    assert expected in error.safe_message
    assert code in error.safe_message
    assert "req-safe-1" in error.safe_message
    assert "prompt and secret" not in error.safe_message
