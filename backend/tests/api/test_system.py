from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_system_info_and_cache_clear_preserve_user_assets(tmp_path: Path) -> None:
    data_dir = tmp_path / "PairForge_Data"
    app = create_app(data_dir, static_dir=tmp_path / "none")

    with TestClient(app) as client:
        cache_file = data_dir / "cache" / "imports" / "preview.docx"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(b"temporary")
        project_file = data_dir / "projects" / "project-1" / "candidate.png"
        project_file.parent.mkdir(parents=True, exist_ok=True)
        project_file.write_bytes(b"keep")

        info = client.get("/api/system/info")
        assert info.status_code == 200
        assert info.json()["name"] == "PairForge"
        assert info.json()["version"] == "0.6.0"
        assert info.json()["repository_url"] == "https://github.com/kaguraaya/PairForge"
        assert info.json()["data_directory"] == str(data_dir)
        assert info.json()["projects_directory"] == str(data_dir / "projects")
        assert info.json()["cache_file_count"] == 1

        cleared = client.post("/api/system/cache/clear")
        assert cleared.status_code == 200
        assert cleared.json() == {"cleared_file_count": 1, "cleared_bytes": 9}
        assert not cache_file.exists()
        assert project_file.read_bytes() == b"keep"
        assert (data_dir / "workbench.sqlite3").exists()


def test_open_directory_is_limited_to_pairforge_data(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "PairForge_Data"
    app = create_app(data_dir, static_dir=tmp_path / "none")
    assets = data_dir / "projects" / "project-1" / "assets"
    assets.mkdir(parents=True)
    opened: list[Path] = []
    monkeypatch.setattr("app.api.system.os.startfile", lambda path: opened.append(Path(path)))

    with TestClient(app) as client:
        response = client.post(
            "/api/system/directory/open", json={"path": str(assets)}
        )
        assert response.status_code == 200
        assert opened == [assets.resolve()]

        outside = tmp_path / "outside"
        outside.mkdir()
        rejected = client.post(
            "/api/system/directory/open", json={"path": str(outside)}
        )
        assert rejected.status_code == 400
