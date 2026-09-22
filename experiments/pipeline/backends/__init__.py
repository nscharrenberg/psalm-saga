"""Maps each of the seven generation conditions to its backend."""

from __future__ import annotations

from experiments.pipeline.backends import (
    agents_room,
    flat,
    flat_with_spec,
    full_pipeline,
    human,
    no_review,
    no_spec,
)
from experiments.pipeline.backends.base import GenerationBackend
from experiments.pipeline.models import Condition

BACKEND_REGISTRY: dict[Condition, GenerationBackend] = {
    "C1": full_pipeline.BACKEND,
    "C2": no_review.BACKEND,
    "C3": flat_with_spec.BACKEND,
    "C4": no_spec.BACKEND,
    "C5": flat.BACKEND,
    "C6": agents_room.BACKEND,
    "C7": human.BACKEND,
}
