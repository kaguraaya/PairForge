import os

from fastapi.testclient import TestClient

from app.main import create_app


QUESTION_MD = """# 题库

## 001｜测试题
- 类型：日漫
- 难度：★★
- 答案字数：3

### 图1生图提示词
第一张图提示

### 图1题面提示
这是图一

### 图2生图提示词
第二张图提示

### 图2题面填空
这是___

### 答案
测试题

### 数字声调拼音
ce4 shi4 ti2

### 谜底拆解
测试拆解
"""


def test_import_preview_confirm_and_estimate_flow(tmp_path) -> None:
    app = create_app(tmp_path / "数据", static_dir=tmp_path / "no-static")
    with TestClient(app) as client:
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("题库.md", QUESTION_MD.encode("utf-8"), "text/markdown")},
        )
        assert preview.status_code == 200
        assert preview.json()["recognized_count"] == 1
        assert preview.json()["error_count"] == 0
        assert client.get("/api/projects").json() == []

        confirmed = client.post(
            "/api/imports/confirm",
            json={"token": preview.json()["token"], "project_name": "测试项目"},
        )
        project_id = confirmed.json()["project_id"]
        assert confirmed.json()["question_count"] == 1
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["candidate_images_directory"].endswith(
            f"projects{os.sep}{project_id}{os.sep}assets"
        )
        assert project["exports_directory"].endswith(
            f"projects{os.sep}{project_id}{os.sep}exports"
        )

        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "alibaba",
                "display_name": "Qwen",
                "base_url": "https://dashscope.aliyuncs.com",
                "model_id": "qwen-image-2.0",
                "api_key": "test-secret-1234",
                "remember_secret": False,
            },
        )
        assert profile.status_code == 200
        payload = profile.json()
        assert payload["secret_configured"] is True
        assert payload["last_four"] == "1234"
        assert "test-secret" not in profile.text

        estimate = client.post(
            "/api/generation/estimate",
            json={
                "project_id": project_id,
                "provider_profile_id": payload["id"],
                "start_code": "001",
                "end_code": "001",
                "q1_outputs": 1,
                "q2_outputs": 1,
            },
        )
        assert estimate.status_code == 200
        assert estimate.json()["total_maximum"] == 2
        assert estimate.json()["estimated_cost_cny"] == "0.40"


def test_prompt_suffixes_are_separate_and_default_empty(tmp_path) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", QUESTION_MD.encode(), "text/markdown")},
        ).json()
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "项目"},
        ).json()["project_id"]
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["q1_prompt_suffix"] == ""
        assert project["q2_prompt_suffix"] == ""
        changed = client.put(
            f"/api/projects/{project_id}/prompts",
            json={"q1_prompt_suffix": "图一通用", "q2_prompt_suffix": "图二通用"},
        ).json()
        assert changed == {"q1_prompt_suffix": "图一通用", "q2_prompt_suffix": "图二通用"}


def test_generation_start_requires_a_readable_credential_before_creating_tasks(
    tmp_path,
) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", QUESTION_MD.encode(), "text/markdown")},
        ).json()
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "项目"},
        ).json()["project_id"]
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "alibaba",
                "display_name": "Qwen",
                "base_url": "https://dashscope.aliyuncs.com",
                "model_id": "qwen-image-2.0",
            },
        ).json()

        response = client.post(
            "/api/generation/start",
            json={
                "project_id": project_id,
                "provider_profile_id": profile["id"],
                "start_code": "001",
                "end_code": "001",
                "q1_outputs": 1,
                "q2_outputs": 1,
            },
        )

        assert response.status_code == 409
        assert "API Key" in response.json()["detail"]
        assert client.get(f"/api/projects/{project_id}/questions").json()[0]["state"] == "imported"


def test_local_api_sets_security_headers_and_rejects_fake_official_host(tmp_path) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
        response = client.post(
            "/api/settings/profiles",
            json={
                "provider": "alibaba",
                "display_name": "伪造服务",
                "base_url": "https://attacker.example",
                "model_id": "qwen-image-2.0",
                "api_key": "never-send-this",
            },
        )
        assert response.status_code == 400
        assert "never-send-this" not in response.text


def test_settings_accepts_documented_alibaba_workspace_host_and_rejects_bad_seed(
    tmp_path,
) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        accepted = client.post(
            "/api/settings/profiles",
            json={
                "provider": "alibaba",
                "display_name": "Wan",
                "base_url": "https://ws123.cn-beijing.maas.aliyuncs.com",
                "model_id": "wan2.7-image",
                "config": {"thinking_mode": True, "watermark": False, "size": "2K"},
            },
        )
        assert accepted.status_code == 200

        rejected = client.post(
            "/api/settings/profiles",
            json={
                "provider": "alibaba",
                "display_name": "Qwen",
                "base_url": "https://dashscope.aliyuncs.com",
                "model_id": "qwen-image-2.0",
                "config": {"seed": 2_147_483_648},
            },
        )
        assert rejected.status_code == 400
        assert "seed" in rejected.json()["detail"]


def test_model_catalog_exposes_official_entry_links_and_candidate_defaults_validate(
    tmp_path,
) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        models = client.get("/api/settings/models").json()
        seedream = next(item for item in models if item["model"].startswith("doubao-seedream-5"))
        qwen = next(item for item in models if item["model"] == "qwen-image-2.0")
        assert "console.volcengine.com" in seedream["api_key_url"]
        assert "help.aliyun.com" in qwen["api_key_url"]
        assert seedream["documentation_url"].startswith("https://")

        accepted = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "Custom",
                "base_url": "https://example.invalid",
                "model_id": "model",
                "config": {
                    "single_output_default": False,
                    "default_q1_outputs": 3,
                    "default_q2_outputs": 2,
                },
            },
        )
        assert accepted.status_code == 200
        rejected = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "Custom",
                "base_url": "https://example.invalid",
                "model_id": "model",
                "config": {"default_q1_outputs": 0},
            },
        )
        assert rejected.status_code == 400


def test_seedream_5_lite_profile_upgrades_legacy_size_and_rejects_too_small_size(
    tmp_path,
) -> None:
    app = create_app(tmp_path / "seedream-size", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        upgraded = client.post(
            "/api/settings/profiles",
            json={
                "provider": "volcengine",
                "display_name": "Seedream 5.0 Lite",
                "base_url": "https://ark.cn-beijing.volces.com",
                "model_id": "doubao-seedream-5-0-lite-260128",
                "config": {"size": "2048x1536"},
            },
        )
        assert upgraded.status_code == 200
        assert upgraded.json()["config"]["size"] == "2304x1728"

        rejected = client.post(
            "/api/settings/profiles",
            json={
                "provider": "volcengine",
                "display_name": "Seedream 5.0 Lite",
                "base_url": "https://ark.cn-beijing.volces.com",
                "model_id": "doubao-seedream-5-0-lite-260128",
                "config": {"size": "1024x1024"},
            },
        )
        assert rejected.status_code == 400
        assert "3,686,400" in rejected.json()["detail"]


def test_seedream_4_5_profile_uses_official_default_and_rejects_3k(tmp_path) -> None:
    app = create_app(tmp_path / "seedream-45-size", static_dir=tmp_path / "none")
    base = {
        "provider": "volcengine",
        "display_name": "Seedream 4.5",
        "base_url": "https://ark.cn-beijing.volces.com",
        "model_id": "doubao-seedream-4-5-251128",
    }
    with TestClient(app) as client:
        upgraded = client.post(
            "/api/settings/profiles",
            json={**base, "config": {"size": "2048x1152"}},
        )
        assert upgraded.status_code == 200
        assert upgraded.json()["config"]["size"] == "2848x1600"

        rejected = client.post(
            "/api/settings/profiles",
            json={**base, "config": {"size": "3K"}},
        )
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == "Seedream 4.5 分辨率档位仅支持 2K、4K"
