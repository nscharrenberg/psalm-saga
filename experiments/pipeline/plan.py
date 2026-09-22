"""YAML plan loading and expansion into `GenerationJob` rows.

See `docs/superpowers/specs/2026-09-22-generation-pipeline-design.md` §3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from experiments.pipeline.models import Condition, GenerationJob, Task

# EXPERIMENTAL_SETUP.md §4: which conditions ever run under which task.
TASK_CONDITION_ELIGIBILITY: dict[Task, frozenset[Condition]] = {
    "A": frozenset({"C1", "C2", "C4", "C5", "C6", "C7"}),
    "B": frozenset({"C1", "C2", "C3"}),
    "C": frozenset({"C1"}),
    "D": frozenset({"C1"}),
}


class PlanError(ValueError):
    """Raised for an invalid plan, e.g. an ineligible task/condition pairing."""


@dataclass(frozen=True)
class TaskSpec:
    """One task's declared conditions and generator families within a plan."""

    conditions: tuple[Condition, ...]
    generators: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """A declarative description of what to generate — see spec §3."""

    name: str
    is_pilot: bool
    corpus_filter: dict[str, Any]
    tasks: dict[Task, TaskSpec]


def load_plan(path: Path) -> Plan:
    """Load and validate a YAML plan file.

    Raises `PlanError` if a task names a condition
    `TASK_CONDITION_ELIGIBILITY` doesn't allow for it.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks: dict[Task, TaskSpec] = {}
    for task_name, task_raw in raw.get("tasks", {}).items():
        conditions = tuple(task_raw["conditions"])
        eligible = TASK_CONDITION_ELIGIBILITY.get(task_name, frozenset())
        for condition in conditions:
            if condition not in eligible:
                raise PlanError(
                    f"Task {task_name} does not run condition {condition} "
                    f"(EXPERIMENTAL_SETUP.md §4: eligible conditions for "
                    f"Task {task_name} are {sorted(eligible)})"
                )
        tasks[task_name] = TaskSpec(conditions=conditions, generators=tuple(task_raw["generators"]))
    return Plan(
        name=raw["name"],
        is_pilot=bool(raw.get("is_pilot", False)),
        corpus_filter=raw.get("corpus_filter") or {},
        tasks=tasks,
    )


def _apply_corpus_filter(corpus: pd.DataFrame, corpus_filter: dict[str, Any]) -> pd.DataFrame:
    """Apply a plan's `corpus_filter` to the loaded corpus.

    Supports `languages: [...]` (restrict to named languages) and
    `sample_per_language: N` (deterministic first-N-per-language, ordered
    by item id, so a pilot plan's item set is reproducible without a
    separate seed). Both may be combined; an empty filter is a no-op.
    """
    df = corpus
    if "languages" in corpus_filter:
        df = df[df["language"].isin(corpus_filter["languages"])]
    if "sample_per_language" in corpus_filter:
        n = corpus_filter["sample_per_language"]
        df = df.sort_values("id").groupby("language", group_keys=False).head(n)
    return df.reset_index(drop=True)


def expand_jobs(plan: Plan, corpus: pd.DataFrame) -> list[GenerationJob]:
    """Expand a plan into the full set of `GenerationJob`s it describes.

    Idempotent: expanding the same plan against the same corpus always
    produces jobs with the same `job_id`s, so inserting the result into
    the registry twice never duplicates work.
    """
    filtered = _apply_corpus_filter(corpus, plan.corpus_filter)
    jobs: list[GenerationJob] = []
    for task, task_spec in plan.tasks.items():
        for _, row in filtered.iterrows():
            for condition in task_spec.conditions:
                for generator in task_spec.generators:
                    jobs.append(
                        GenerationJob(
                            plan_name=plan.name,
                            task=task,
                            condition=condition,
                            item_id=row["id"],
                            generator_family=generator,
                            language=row["language"],
                            is_pilot=plan.is_pilot,
                        )
                    )
    return jobs
