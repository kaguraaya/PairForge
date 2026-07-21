import os
import sys
from dataclasses import dataclass
from pathlib import Path


DATA_DIRECTORY_NAME = "PairForge_Data"


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    configured = os.environ.get("WORKBENCH_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return application_root() / DATA_DIRECTORY_NAME


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"
