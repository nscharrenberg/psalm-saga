"""Tests for `experiments.pipeline.plan`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from experiments.pipeline.plan import PlanError, expand_jobs, load_plan


def _write_plan(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _sample_corpus() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"id": "satire_a", "language": "english", "genre_bucket": "satire"},
            {"id": "satire_b", "language": "english", "genre_bucket": "satire"},
            {"id": "gothic_a", "language": "dutch", "genre_bucket": "gothic"},
        ]
    )


def test_load_plan_parses_tasks_and_conditions(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {
            "name": "pilot",
            "is_pilot": True,
            "corpus_filter": {"sample_per_language": 1},
            "tasks": {
                "A": {"conditions": ["C1", "C5"], "generators": ["frontier"]},
                "B": {"conditions": ["C1"], "generators": ["frontier", "open_weight"]},
            },
        },
    )

    plan = load_plan(path)

    assert plan.name == "pilot"
    assert plan.is_pilot is True
    assert plan.corpus_filter == {"sample_per_language": 1}
    assert plan.tasks["A"].conditions == ("C1", "C5")
    assert plan.tasks["B"].generators == ("frontier", "open_weight")


def test_load_plan_defaults_is_pilot_to_false(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {"name": "confirmatory", "tasks": {"C": {"conditions": ["C1"], "generators": ["frontier"]}}},
    )

    plan = load_plan(path)

    assert plan.is_pilot is False
    assert plan.corpus_filter == {}


def test_load_plan_rejects_ineligible_condition(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {"name": "bad", "tasks": {"A": {"conditions": ["C3"], "generators": ["frontier"]}}},
    )

    with pytest.raises(PlanError, match="C3"):
        load_plan(path)


def test_expand_jobs_produces_the_cross_product_of_items_conditions_and_generators(
    tmp_path: Path,
) -> None:
    path = _write_plan(
        tmp_path,
        {
            "name": "pilot",
            "tasks": {"A": {"conditions": ["C1", "C5"], "generators": ["frontier", "open_weight"]}},
        },
    )
    plan = load_plan(path)

    jobs = expand_jobs(plan, _sample_corpus())

    # 3 items x 2 conditions x 2 generators = 12 jobs
    assert len(jobs) == 12
    assert {job.item_id for job in jobs} == {"satire_a", "satire_b", "gothic_a"}
    assert {job.condition for job in jobs} == {"C1", "C5"}
    assert {job.generator_family for job in jobs} == {"frontier", "open_weight"}
    assert all(job.task == "A" for job in jobs)
    assert all(job.plan_name == "pilot" for job in jobs)


def test_expand_jobs_is_idempotent(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path, {"name": "pilot", "tasks": {"A": {"conditions": ["C1"], "generators": ["frontier"]}}}
    )
    plan = load_plan(path)
    corpus = _sample_corpus()

    first = {job.job_id for job in expand_jobs(plan, corpus)}
    second = {job.job_id for job in expand_jobs(plan, corpus)}

    assert first == second


def test_expand_jobs_applies_sample_per_language_filter(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        {
            "name": "pilot",
            "corpus_filter": {"sample_per_language": 1},
            "tasks": {"A": {"conditions": ["C1"], "generators": ["frontier"]}},
        },
    )
    plan = load_plan(path)

    jobs = expand_jobs(plan, _sample_corpus())

    assert len(jobs) == 2  # 1 per language, 2 languages
    assert {job.item_id for job in jobs} == {"satire_a", "gothic_a"}
