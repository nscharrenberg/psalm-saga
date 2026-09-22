"""Resolves a `GenerationJob`'s input content from the fixed data-directory
convention under `experiments/data/` — see spec §4.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from experiments.pipeline.models import GenerationJob, Task

InputKind = Literal["premise", "gold_spec", "scratch_spec", "source_text"]

TASK_INPUT_KIND: dict[Task, InputKind] = {
    "A": "premise",
    "B": "gold_spec",
    "C": "source_text",
    "D": "scratch_spec",
}


@dataclass(frozen=True)
class ResolvedInput:
    """The resolved content a backend consumes for one job's task."""

    kind: InputKind
    content: str
    source_path: Path


class InputNotFoundError(FileNotFoundError):
    """Raised when a job's required input file doesn't exist yet.

    Expected until premises/gold specs/scratch specs are authored as
    separate follow-up work (spec §1, §12) — a job simply can't run until
    then, and this error identifies exactly which file is missing.
    """


class InputResolver:
    """Looks up a job's input content by the fixed data-directory convention."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def _path_for(self, job: GenerationJob) -> Path:
        kind = TASK_INPUT_KIND[job.task]
        if kind == "premise":
            return self.data_dir / "premises" / f"{job.item_id}.md"
        if kind == "gold_spec":
            return self.data_dir / "specs" / "gold" / f"{job.item_id}.md"
        if kind == "scratch_spec":
            return self.data_dir / "specs" / "scratch" / f"{job.item_id}.md"
        return self.data_dir / "stories" / job.language / f"{job.item_id}.txt"

    def resolve(self, job: GenerationJob) -> ResolvedInput:
        """Read and return this job's input, or raise `InputNotFoundError`."""
        kind = TASK_INPUT_KIND[job.task]
        path = self._path_for(job)
        if not path.is_file():
            raise InputNotFoundError(
                f"No {kind} input for job {job.job_id} (item {job.item_id!r}): expected {path}"
            )
        return ResolvedInput(kind=kind, content=path.read_text(encoding="utf-8"), source_path=path)
