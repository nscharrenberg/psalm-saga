"""Core data model for the generation pipeline: jobs and their results.

A `GenerationJob` is the atomic unit of work the rest of the pipeline
revolves around — see `docs/superpowers/specs/
2026-09-22-generation-pipeline-design.md` §2.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

Task = Literal["A", "B", "C", "D"]
Condition = Literal["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
JobStatus = Literal["pending", "running", "done", "failed", "abandoned"]


@dataclass(frozen=True)
class GenerationJob:
    """One unit of generation work: one item, run through one condition and
    task, for one generator family and language.
    """

    plan_name: str
    task: Task
    condition: Condition
    item_id: str
    generator_family: str
    language: str
    replicate: int = 0
    is_pilot: bool = False
    length_range: str | None = None
    """Word-count range (`MIN-MAX`) the story should land in. Not part of identity."""

    @property
    def job_id(self) -> str:
        """Stable content hash of this job's identity fields.

        Two jobs with the same identity always produce the same `job_id` —
        this is what makes plan expansion and registry inserts idempotent
        (re-expanding a plan never duplicates a job already on record).
        """
        identity = (
            self.plan_name,
            self.task,
            self.condition,
            self.item_id,
            self.generator_family,
            self.language,
            self.replicate,
            self.is_pilot,
        )
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()[:16]


@dataclass(frozen=True)
class GenerationResult:
    """What a `GenerationBackend` hands back after running one job.

    The runner (not the backend) is responsible for writing these onto
    disk — keeping backends pure and independently testable.
    """

    artifacts: dict[str, str]
    """Relative filename -> text content, to be written into the job's output dir."""
    trace: list[dict[str, Any]]
    """The full raw message trace, one dict per model call in/out."""
    config: dict[str, Any]
    """Reproducibility snapshot: model id, decoding params, seed, prompt hash, etc."""


class JobAbandoned(Exception):  # noqa: N818 — named by its domain meaning, not an error suffix
    """Every story attempt for a job was abandoned by the review loop.

    Carries the artifacts and trace of all attempts so the runner can persist
    them as evidence before recording the job as `abandoned`.
    """

    def __init__(
        self,
        reason: str,
        *,
        artifacts: dict[str, str],
        trace: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.artifacts = artifacts
        self.trace = trace
        self.config = config


class JobFailed(RuntimeError):  # noqa: N818 — pairs with JobAbandoned; maps to status `failed`
    """A story attempt hit a real error (an exception, or no `DONE.md`/`ABANDONED.md`).

    Carries the artifacts and trace of every attempt made so far so the runner
    can persist them as evidence before recording the job as `failed`.
    """

    def __init__(
        self,
        message: str,
        *,
        artifacts: dict[str, str],
        trace: list[dict[str, Any]],
        config: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.artifacts = artifacts
        self.trace = trace
        self.config = config
