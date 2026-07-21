import base64
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import ProviderProfile
from app.main import create_app
from app.providers.base import GenerationResult, ImageSource
from app.providers.errors import ProviderError, ProviderErrorCategory


def image_b64(color: str) -> str:
    output = BytesIO()
    Image.new("RGB", (32, 32), color).save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode()


class FakeProvider:
    async def generate(self, request):
        if "002-图一" in request.prompt:
            values = (image_b64("red"), image_b64("blue"))
        else:
            values = (image_b64("green"),)
        return GenerationResult(tuple(ImageSource(b64_json=value) for value in values), "fake-request")


class KeyAwareProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def generate(self, _request):
        if self.api_key == "bad-primary-1111":
            raise ProviderError(ProviderErrorCategory.AUTHENTICATION, "API 密钥无效")
        return GenerationResult((ImageSource(b64_json=image_b64("green")),), "backup")


class RecordingProvider:
    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return GenerationResult((ImageSource(b64_json=image_b64("green")),), "recorded")


class RateLimitedOnceProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, _request):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError(
                ProviderErrorCategory.RATE_LIMIT,
                "请求过于频繁",
                retry_after_seconds=1,
            )
        return GenerationResult((ImageSource(b64_json=image_b64("green")),), "recovered")


BANK = """# 测试题库
## 001｜第一题
### 图1生图提示词
001-图一
### 图1题面提示
一
### 图2生图提示词
001-图二
### 图2题面填空
___
### 答案
答案一
### 数字声调拼音
1
### 谜底拆解
一
### 基本信息
类型：测试 ｜ 难度：一 ｜ 答案字数：3

## 002｜第二题
### 图1生图提示词
002-图一
### 图1题面提示
二
### 图2生图提示词
002-图二
### 图2题面填空
___
### 答案
答案二
### 数字声调拼音
2
### 谜底拆解
二
### 基本信息
类型：测试 ｜ 难度：一 ｜ 答案字数：3
"""


def wait_for(client: TestClient, project_id: str, predicate, timeout: float = 8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        questions = client.get(f"/api/projects/{project_id}/questions").json()
        if predicate(questions):
            return questions
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for state: {questions}")


def test_two_questions_never_cross_and_single_results_auto_advance(tmp_path) -> None:
    app = create_app(tmp_path / "data", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        app.state.provider_factory = lambda _profile, _key: FakeProvider()
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", BANK.encode(), "text/markdown")},
        ).json()
        assert preview["error_count"] == 0
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "E2E"},
        ).json()["project_id"]
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "fake",
                "display_name": "Fake",
                "base_url": "https://example.invalid",
                "model_id": "fake-image",
                "api_key": "fake-key",
                "config": {"max_outputs": 2, "default_size": "32x32"},
            },
        ).json()
        response = client.post(
            "/api/generation/start",
            json={
                "project_id": project_id,
                "provider_profile_id": profile["id"],
                "start_code": "001",
                "end_code": "002",
                "q1_outputs": 2,
                "q2_outputs": 2,
                "parallelism": 6,
            },
        )
        assert response.status_code == 200

        questions = wait_for(
            client,
            project_id,
            lambda items: items[0]["state"] == "completed" and items[1]["state"] == "image1_review",
        )
        first, second = questions
        progress = client.get(
            f"/api/generation/projects/{project_id}/latest-batch"
        ).json()
        assert progress["expected_stage_count"] == 4
        assert progress["completed_stage_count"] == 3
        assert progress["progress_percent"] == 75
        assert progress["completed_question_count"] == 1
        assert progress["review_question_count"] == 1
        assert progress["scheduler_parallelism"] == 6
        assert first["selected_image1_id"] and first["selected_image2_id"]
        first_q2 = next(asset for asset in first["assets"] if asset["stage"] == "image2")
        assert first_q2["reference_asset_id"] == first["selected_image1_id"]
        assert all(asset["id"] not in {first["selected_image1_id"], first["selected_image2_id"]} for asset in second["assets"])

        second_q1 = next(asset for asset in second["assets"] if asset["stage"] == "image1")
        selected = client.post(
            "/api/generation/select",
            json={"question_id": second["id"], "asset_id": second_q1["id"], "stage": "image1"},
        )
        assert selected.status_code == 200
        questions = wait_for(client, project_id, lambda items: items[1]["state"] == "completed")
        second = questions[1]
        progress = client.get(
            f"/api/generation/projects/{project_id}/latest-batch"
        ).json()
        assert progress["completed_stage_count"] == 4
        assert progress["progress_percent"] == 100
        assert progress["completed_question_count"] == 2
        second_q2 = next(asset for asset in second["assets"] if asset["stage"] == "image2")
        assert second_q2["reference_asset_id"] == second["selected_image1_id"]
        assert second_q2["reference_asset_id"] != first["selected_image1_id"]

        exported = client.post("/api/exports", json={"project_id": project_id})
        assert exported.status_code == 200
        export_dir = Path(exported.json()["directory"])
        final_images = list((export_dir / "final_images").iterdir())
        assert len(final_images) == 4
        assert {path.name for path in final_images} == {
            "001__答案一__01.png",
            "001__答案一__02.png",
            "002__答案二__01.png",
            "002__答案二__02.png",
        }
        assert (export_dir / "manifest.csv").is_file()
        assert (export_dir / "manifest.json").is_file()


def test_invalid_primary_key_fails_over_to_same_profile_backup(tmp_path) -> None:
    app = create_app(tmp_path / "failover", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        app.state.provider_factory = lambda _profile, key: KeyAwareProvider(key)
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", BANK.encode(), "text/markdown")},
        ).json()
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "Failover"},
        ).json()["project_id"]
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "fake",
                "display_name": "Fake Pool",
                "base_url": "https://example.invalid",
                "model_id": "fake-image",
                "api_key": "bad-primary-1111",
                "config": {"max_outputs": 1, "default_size": "32x32"},
            },
        ).json()
        backup = client.post(
            f"/api/settings/profiles/{profile['id']}/credentials",
            json={
                "label": "备用 Key",
                "priority": 20,
                "api_key": "working-backup-2222",
                "manual_remaining_images": 10,
            },
        )
        assert backup.status_code == 200
        started = client.post(
            "/api/generation/start",
            json={
                "project_id": project_id,
                "provider_profile_id": profile["id"],
                "start_code": "001",
                "end_code": "001",
                "q1_outputs": 1,
                "q2_outputs": 1,
            },
        ).json()
        wait_for(client, project_id, lambda items: items[0]["state"] == "completed")
        credentials = client.get(
            f"/api/settings/profiles/{profile['id']}/credentials"
        ).json()
        assert credentials[0]["status"] == "invalid"
        assert credentials[1]["status"] == "active"
        assert credentials[1]["manual_remaining_images"] == 8
        batch = client.get(f"/api/generation/batches/{started['batch_id']}").json()
        assert batch["status"] == "completed"


def test_rate_limit_can_pause_and_resume_without_losing_position(tmp_path) -> None:
    app = create_app(tmp_path / "rate-limit", static_dir=tmp_path / "none")
    provider = RateLimitedOnceProvider()
    with TestClient(app) as client:
        app.state.provider_factory = lambda _profile, _key: provider
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", BANK.encode(), "text/markdown")},
        ).json()
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "Rate limit"},
        ).json()["project_id"]
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "fake",
                "display_name": "Fake limited",
                "base_url": "https://example.invalid",
                "model_id": "fake-image",
                "api_key": "fake-key",
                "config": {"max_outputs": 1, "default_size": "32x32"},
            },
        ).json()
        started = client.post(
            "/api/generation/start",
            json={
                "project_id": project_id,
                "provider_profile_id": profile["id"],
                "start_code": "001",
                "end_code": "001",
                "q1_outputs": 1,
                "q2_outputs": 1,
            },
        ).json()

        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            progress = client.get(
                f"/api/generation/batches/{started['batch_id']}"
            ).json()
            if progress["retry_waiting_count"] == 1:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("rate-limited task was not scheduled for retry")

        paused = client.post(
            f"/api/generation/batches/{started['batch_id']}/pause"
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert paused.json()["can_resume"] is True
        time.sleep(1.1)
        assert provider.calls == 1

        resumed = client.post(
            f"/api/generation/batches/{started['batch_id']}/resume"
        )
        assert resumed.status_code == 200
        wait_for(client, project_id, lambda items: items[0]["state"] == "completed")
        assert provider.calls == 3


def test_legacy_seedream_profile_is_normalized_again_at_request_time(tmp_path) -> None:
    app = create_app(tmp_path / "legacy-size", static_dir=tmp_path / "none")
    recorder = RecordingProvider()
    with TestClient(app) as client:
        app.state.provider_factory = lambda _profile, _key: recorder
        preview = client.post(
            "/api/imports/preview",
            files={"file": ("bank.md", BANK.encode(), "text/markdown")},
        ).json()
        project_id = client.post(
            "/api/imports/confirm",
            json={"token": preview["token"], "project_name": "Legacy size"},
        ).json()["project_id"]
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": project_id,
                "provider": "volcengine",
                "display_name": "Seedream 5.0 Lite",
                "base_url": "https://ark.cn-beijing.volces.com",
                "model_id": "doubao-seedream-5-0-lite-260128",
                "api_key": "fake-key",
                "config": {"size": "2048x2048"},
            },
        ).json()

        # Simulate the persisted value written by an older executable.
        with Session(app.state.engine) as session:
            stored = session.get(ProviderProfile, profile["id"])
            assert stored is not None
            stored.config = {**(stored.config or {}), "size": "2048x1536"}
            session.commit()

        started = client.post(
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
        assert started.status_code == 200
        wait_for(client, project_id, lambda items: items[0]["state"] == "completed")

    assert len(recorder.requests) == 2
    assert {request.size for request in recorder.requests} == {"2304x1728"}
