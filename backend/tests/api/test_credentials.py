from fastapi.testclient import TestClient

from app.main import create_app


def test_profile_accepts_multiple_write_only_keys(tmp_path) -> None:
    data_dir = tmp_path / "data"
    app = create_app(data_dir, static_dir=tmp_path / "none")
    with TestClient(app) as client:
        profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "volcengine",
                "display_name": "Seedream",
                "base_url": "https://ark.cn-beijing.volces.com",
                "model_id": "doubao-seedream-5-0-lite-260128",
                "api_key": "primary-secret-1111",
                "remember_secret": False,
            },
        ).json()
        assert len(profile["credentials"]) == 1
        second = client.post(
            f"/api/settings/profiles/{profile['id']}/credentials",
            json={
                "label": "备用账户",
                "account_label": "账号 B",
                "priority": 20,
                "api_key": "backup-secret-2222",
                "remember_secret": False,
                "manual_remaining_images": 200,
            },
        )
        assert second.status_code == 200
        listed = client.get(f"/api/settings/profiles/{profile['id']}/credentials")
        assert listed.status_code == 200
        assert [item["last_four"] for item in listed.json()] == ["1111", "2222"]
        assert "primary-secret" not in listed.text
        assert "backup-secret" not in listed.text
        assert all(item["profile_id"] == profile["id"] for item in listed.json())
        refreshed_profile = client.get("/api/settings/profiles").json()[0]
        assert refreshed_profile["credentials"][0]["local_generated_images"] == 0
        assert refreshed_profile["credentials"][0]["local_estimated_cost_cny"] == "0.00"
    database_bytes = b"".join(
        path.read_bytes() for path in data_dir.iterdir() if path.is_file()
    )
    assert b"primary-secret" not in database_bytes
    assert b"backup-secret" not in database_bytes


def test_saved_key_can_be_deleted_and_readded_without_losing_history_slot(tmp_path) -> None:
    app = create_app(tmp_path / "delete", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "可删除 Key 的服务",
                "base_url": "https://example.invalid/v1",
                "model_id": "model",
                "api_key": "first-secret-1111",
                "remember_secret": False,
            },
        ).json()
        credential_id = profile["credentials"][0]["id"]

        deleted = client.delete(
            f"/api/settings/profiles/{profile['id']}/credentials/{credential_id}"
        )

        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}
        assert app.state.secret_store.get(credential_id) is None
        assert client.get(
            f"/api/settings/profiles/{profile['id']}/credentials"
        ).json() == []
        refreshed = client.get("/api/settings/profiles").json()[0]
        assert refreshed["secret_configured"] is False
        assert refreshed["credentials"] == []

        restored = client.post(
            f"/api/settings/profiles/{profile['id']}/credentials",
            json={
                "label": "主 Key",
                "priority": 10,
                "api_key": "replacement-secret-2222",
                "remember_secret": False,
            },
        )
        assert restored.status_code == 200
        assert restored.json()["id"] == credential_id
        assert restored.json()["enabled"] is True
        assert restored.json()["last_four"] == "2222"
        assert len(client.get("/api/settings/profiles").json()[0]["credentials"]) == 1


def test_volcengine_profile_accepts_only_known_api_modes(tmp_path) -> None:
    app = create_app(tmp_path / "modes", static_dir=tmp_path / "none")
    base = {
        "provider": "volcengine",
        "display_name": "Seedream",
        "base_url": "https://ark.cn-beijing.volces.com",
        "model_id": "doubao-seedream-5-0-lite-260128",
    }
    with TestClient(app) as client:
        agent_plan = client.post(
            "/api/settings/profiles",
            json={**base, "config": {"api_mode": "agent_plan"}},
        )
        assert agent_plan.status_code == 200
        assert agent_plan.json()["config"]["api_mode"] == "agent_plan"

        invalid = client.post(
            "/api/settings/profiles",
            json={**base, "config": {"api_mode": "unexpected"}},
        )
        assert invalid.status_code == 400


def test_models_publish_production_support_level(tmp_path) -> None:
    app = create_app(tmp_path / "models", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        models = client.get("/api/settings/models").json()
    support = {item["model"]: item["support_level"] for item in models}
    assert support["doubao-seedream-5-0-lite-260128"] == "optimized"
    assert support["qwen-image-2.0"] == "testing"
    assert support["wan2.7-image"] == "testing"


def test_credential_cannot_be_moved_or_edited_through_another_profile(tmp_path) -> None:
    app = create_app(tmp_path / "cross", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        def profile(name: str):
            return client.post(
                "/api/settings/profiles",
                json={
                    "provider": "custom",
                    "display_name": name,
                    "base_url": "https://example.invalid",
                    "model_id": "model",
                    "api_key": f"{name}-secret-1234",
                },
            ).json()

        first = profile("first")
        second = profile("second")
        credential_id = first["credentials"][0]["id"]
        response = client.post(
            f"/api/settings/profiles/{second['id']}/credentials",
            json={
                "id": credential_id,
                "label": "越权修改",
                "api_key": "replacement-secret-9999",
            },
        )
        assert response.status_code == 409
        assert "replacement-secret" not in response.text

        delete_response = client.delete(
            f"/api/settings/profiles/{second['id']}/credentials/{credential_id}"
        )
        assert delete_response.status_code == 404
        assert len(
            client.get(f"/api/settings/profiles/{first['id']}/credentials").json()
        ) == 1


def test_profile_rejects_secrets_hidden_inside_extension_config(tmp_path) -> None:
    app = create_app(tmp_path / "config", static_dir=tmp_path / "none")
    with TestClient(app) as client:
        response = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "Custom",
                "base_url": "https://example.invalid",
                "model_id": "model",
                "config": {"nested": {"api-key": "must-not-persist"}},
            },
        )
        assert response.status_code == 400
        assert "must-not-persist" not in response.text


def test_session_only_credential_is_marked_unavailable_after_restart(tmp_path) -> None:
    data_dir = tmp_path / "restart"
    first_app = create_app(data_dir, static_dir=tmp_path / "none")
    with TestClient(first_app) as client:
        profile = client.post(
            "/api/settings/profiles",
            json={
                "provider": "custom",
                "display_name": "Session only",
                "base_url": "https://example.invalid/v1",
                "model_id": "model",
                "api_key": "session-only-secret-8877",
                "remember_secret": False,
            },
        ).json()
        profile_id = profile["id"]
        assert profile["secret_configured"] is True
        assert profile["session_only"] is True

    restarted_app = create_app(data_dir, static_dir=tmp_path / "none")
    with TestClient(restarted_app) as client:
        profile = client.get("/api/settings/profiles").json()[0]
        assert profile["id"] == profile_id
        assert profile["secret_configured"] is False
        assert profile["credentials"][0]["secret_configured"] is False
        assert profile["credentials"][0]["status"] == "invalid"
        assert "session-only-secret" not in client.get("/api/settings/profiles").text
