"""Tests for `experiments.pipeline.models`."""

from __future__ import annotations

from experiments.pipeline.models import GenerationJob


def _job(**overrides: object) -> GenerationJob:
    fields = {
        "plan_name": "pilot",
        "task": "A",
        "condition": "C1",
        "item_id": "satire_the_happy_prince",
        "generator_family": "frontier",
        "language": "english",
    }
    fields.update(overrides)
    return GenerationJob(**fields)  # type: ignore[arg-type]


def test_job_id_is_deterministic_for_the_same_identity() -> None:
    assert _job().job_id == _job().job_id


def test_job_id_differs_when_any_identity_field_differs() -> None:
    base = _job()
    assert base.job_id != _job(condition="C2").job_id
    assert base.job_id != _job(item_id="satire_a_modest_proposal").job_id
    assert base.job_id != _job(generator_family="open_weight").job_id
    assert base.job_id != _job(language="dutch").job_id
    assert base.job_id != _job(replicate=1).job_id
    assert base.job_id != _job(is_pilot=True).job_id
    assert base.job_id != _job(plan_name="confirmatory").job_id


def test_job_id_is_a_short_hex_string() -> None:
    job_id = _job().job_id
    assert len(job_id) == 16
    int(job_id, 16)  # raises ValueError if not valid hex
