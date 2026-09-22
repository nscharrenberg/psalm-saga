"""Tests for `experiments.pipeline.backends`."""

from __future__ import annotations

import pytest

from experiments.pipeline.backends.base import NotImplementedBackend
from experiments.pipeline.models import GenerationJob


def _job(condition: str) -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task="A",
        condition=condition,  # type: ignore[arg-type]
        item_id="satire_the_happy_prince",
        generator_family="frontier",
        language="english",
    )


def test_not_implemented_backend_raises_naming_the_condition() -> None:
    backend = NotImplementedBackend("C4")

    with pytest.raises(NotImplementedError, match="C4"):
        backend.run(_job("C4"), input_ref=None)  # type: ignore[arg-type]


def test_stub_modules_export_a_backend_for_their_condition() -> None:
    from experiments.pipeline.backends import agents_room, flat, flat_with_spec, human, no_review, no_spec

    assert isinstance(no_review.BACKEND, NotImplementedBackend)
    assert isinstance(flat_with_spec.BACKEND, NotImplementedBackend)
    assert isinstance(no_spec.BACKEND, NotImplementedBackend)
    assert isinstance(flat.BACKEND, NotImplementedBackend)
    assert isinstance(agents_room.BACKEND, NotImplementedBackend)
    assert isinstance(human.BACKEND, NotImplementedBackend)

    for module, condition in (
        (no_review, "C2"), (flat_with_spec, "C3"), (no_spec, "C4"),
        (flat, "C5"), (agents_room, "C6"), (human, "C7"),
    ):
        with pytest.raises(NotImplementedError, match=condition):
            module.BACKEND.run(_job(condition), input_ref=None)
