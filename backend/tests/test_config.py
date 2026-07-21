from pathlib import Path

from app import config


def test_default_data_directory_is_portable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WORKBENCH_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "application_root", lambda: tmp_path / "PairForge")

    assert config.default_data_dir() == tmp_path / "PairForge" / "PairForge_Data"


def test_environment_can_override_portable_directory(monkeypatch, tmp_path: Path) -> None:
    custom = tmp_path / "自定义数据"
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(custom))

    assert config.default_data_dir() == custom.resolve()
