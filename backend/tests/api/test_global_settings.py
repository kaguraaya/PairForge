from fastapi.testclient import TestClient

from app.main import create_app


BANK = """# 题库

## 001｜测试题
### 图1生图提示词
第一张图
### 图1题面提示
图一
### 图2生图提示词
第二张图
### 图2题面填空
图二
### 答案
测试题
### 数字声调拼音
ce4 shi4 ti2
### 谜底拆解
测试
"""


def import_project(client: TestClient, name: str, marker: str) -> str:
    content = BANK.replace("测试题", f"测试题{marker}")
    preview = client.post(
        "/api/imports/preview",
        files={"file": (f"{name}.md", content.encode(), "text/markdown")},
    ).json()
    return client.post(
        "/api/imports/confirm",
        json={"token": preview["token"], "project_name": name},
    ).json()["project_id"]


def test_profiles_credentials_and_prompts_are_reused_across_projects(tmp_path) -> None:
    app = create_app(tmp_path / "global", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        first_project = import_project(client, "项目一", "一")
        profile = client.post(
            "/api/settings/profiles",
            json={
                "project_id": first_project,
                "provider": "custom",
                "display_name": "全局服务",
                "base_url": "https://example.invalid",
                "model_id": "global-model",
                "api_key": "global-primary-1111",
                "remember_secret": False,
                "config": {"default_q1_outputs": 2, "default_q2_outputs": 1},
            },
        ).json()
        backup = client.post(
            f"/api/settings/profiles/{profile['id']}/credentials",
            json={
                "label": "全局备用 Key",
                "priority": 20,
                "api_key": "global-backup-2222",
                "remember_secret": False,
            },
        ).json()
        saved_prompts = client.put(
            "/api/settings/prompts",
            json={"q1_prompt_suffix": "全局图一", "q2_prompt_suffix": "全局图二"},
        )
        assert saved_prompts.status_code == 200

        second_project = import_project(client, "项目二", "二")
        second = client.get(f"/api/projects/{second_project}").json()
        assert second["selected_provider_profile_id"] == profile["id"]
        assert second["q1_prompt_suffix"] == "全局图一"
        assert second["q2_prompt_suffix"] == "全局图二"

        profiles = client.get(
            f"/api/settings/profiles?project_id={second_project}"
        ).json()
        reused = next(item for item in profiles if item["id"] == profile["id"])
        assert reused["project_id"] is None
        assert [item["id"] for item in reused["credentials"]] == [
            profile["credentials"][0]["id"],
            backup["id"],
        ]
        assert all(item["secret_configured"] for item in reused["credentials"])

        estimate = client.post(
            "/api/generation/estimate",
            json={
                "project_id": second_project,
                "provider_profile_id": profile["id"],
                "start_code": "001",
                "end_code": "001",
                "q1_outputs": 1,
                "q2_outputs": 1,
            },
        )
        assert estimate.status_code == 200


def test_each_project_keeps_its_selected_global_profile(tmp_path) -> None:
    app = create_app(tmp_path / "selection", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        first_profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "服务 A",
                "base_url": "https://a.example.invalid",
                "model_id": "model-a",
            },
        ).json()
        second_profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "服务 B",
                "base_url": "https://b.example.invalid",
                "model_id": "model-b",
            },
        ).json()
        first_project = import_project(client, "项目一", "甲")
        second_project = import_project(client, "项目二", "乙")

        second_selected = client.put(
            f"/api/projects/{second_project}/provider-profile",
            json={"profile_id": second_profile["id"]},
        )
        first_selected = client.put(
            f"/api/projects/{first_project}/provider-profile",
            json={"profile_id": first_profile["id"]},
        )

        assert first_selected.status_code == 200
        assert second_selected.status_code == 200
        assert (
            client.get(f"/api/projects/{first_project}").json()[
                "selected_provider_profile_id"
            ]
            == first_profile["id"]
        )
        assert (
            client.get(f"/api/projects/{second_project}").json()[
                "selected_provider_profile_id"
            ]
            == second_profile["id"]
        )

        newest_project = import_project(client, "项目三", "丙")
        assert (
            client.get(f"/api/projects/{newest_project}").json()[
                "selected_provider_profile_id"
            ]
            == first_profile["id"]
        )


def test_global_service_can_be_deleted_and_projects_use_a_replacement(tmp_path) -> None:
    app = create_app(tmp_path / "delete-service", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        first_profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "保留服务",
                "base_url": "https://keep.example.invalid",
                "model_id": "keep-model",
                "api_key": "keep-secret-1111",
            },
        ).json()
        deleted_profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "待删除服务",
                "base_url": "https://delete.example.invalid",
                "model_id": "delete-model",
                "api_key": "delete-secret-2222",
            },
        ).json()
        deleted_credential_id = deleted_profile["credentials"][0]["id"]
        project_id = import_project(client, "使用待删除服务的项目", "丁")
        assert (
            client.get(f"/api/projects/{project_id}").json()[
                "selected_provider_profile_id"
            ]
            == deleted_profile["id"]
        )

        response = client.delete(f"/api/settings/profiles/{deleted_profile['id']}")

        assert response.status_code == 200
        assert response.json() == {
            "deleted": True,
            "replacement_profile_id": first_profile["id"],
            "affected_project_count": 1,
        }
        assert app.state.secret_store.get(deleted_credential_id) is None
        assert [item["id"] for item in client.get("/api/settings/profiles").json()] == [
            first_profile["id"]
        ]
        assert (
            client.get(f"/api/projects/{project_id}").json()[
                "selected_provider_profile_id"
            ]
            == first_profile["id"]
        )
        assert (
            client.get(
                f"/api/settings/profiles/{deleted_profile['id']}/credentials"
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/settings/profiles",
                json={
                    **deleted_profile,
                    "project_id": project_id,
                    "api_key": None,
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/generation/estimate",
                json={
                    "project_id": project_id,
                    "provider_profile_id": deleted_profile["id"],
                    "start_code": "001",
                    "end_code": "001",
                    "q1_outputs": 1,
                    "q2_outputs": 1,
                },
            ).status_code
            == 404
        )
