"""The `GenerationBackend` protocol and a shared stub for unbuilt conditions."""

from __future__ import annotations

from typing import Protocol

from experiments.pipeline.models import Condition, GenerationJob, GenerationResult
from experiments.pipeline.resolver import ResolvedInput


class GenerationBackend(Protocol):
    """Runs one `GenerationJob` given its resolved input and returns a `GenerationResult`."""

    def run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult: ...


class NotImplementedBackend:
    """A stub backend for a condition not yet built.

    Raises immediately and by name, so a plan naming an unbuilt condition
    fails loudly at run time instead of silently producing nothing — see
    spec §5.
    """

    def __init__(self, condition: Condition) -> None:
        self._condition = condition

    def run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult:
        raise NotImplementedError(f"{self._condition} backend is not yet implemented")
