from dataclasses import dataclass
from pathlib import Path

from app.domain.enums import GenerationStage


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "workbench.sqlite3"

    def candidate_dir(self, stage: GenerationStage) -> Path:
        name = "q1_candidates" if stage is GenerationStage.IMAGE1 else "q2_candidates"
        return self.root / "assets" / name

    @property
    def rejected_dir(self) -> Path:
        return self.root / "assets" / "rejected"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.candidate_dir(GenerationStage.IMAGE1).mkdir(parents=True, exist_ok=True)
        self.candidate_dir(GenerationStage.IMAGE2).mkdir(parents=True, exist_ok=True)
        self.rejected_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

