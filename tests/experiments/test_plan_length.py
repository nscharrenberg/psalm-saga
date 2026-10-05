# tests/experiments/test_plan_length.py
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from experiments.pipeline.plan import PlanError, expand_jobs, load_plan


def _plan_file(tmp_path: Path, **extra: object) -> Path:
    path = tmp_path / "plan.yaml"
    body = {"name": "pilot", "tasks": {"A": {"conditions": ["C1"], "generators": ["frontier"]}}, **extra}
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def _corpus() -> pd.DataFrame:
    return pd.DataFrame(
        [{"id": "a", "language": "english", "word_count": 300}, {"id": "b", "language": "dutch", "word_count": 1000}]
    )


def test_expansion_sets_each_jobs_band_from_its_word_count(tmp_path: Path) -> None:
    jobs = expand_jobs(load_plan(_plan_file(tmp_path)), _corpus())
    by_item = {job.item_id: job.length_range for job in jobs}
    assert by_item == {"a": "270-330", "b": "900-1100"}


def test_plan_length_overrides_the_per_item_band(tmp_path: Path) -> None:
    plan = load_plan(_plan_file(tmp_path, length="500-600"))
    assert {job.length_range for job in expand_jobs(plan, _corpus())} == {"500-600"}


def test_invalid_plan_length_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PlanError):
        load_plan(_plan_file(tmp_path, length="600-500"))


def test_length_is_not_part_of_job_identity(tmp_path: Path) -> None:
    with_override = expand_jobs(load_plan(_plan_file(tmp_path, length="500-600")), _corpus())
    without = expand_jobs(load_plan(_plan_file(tmp_path)), _corpus())
    assert [j.job_id for j in with_override] == [j.job_id for j in without]
