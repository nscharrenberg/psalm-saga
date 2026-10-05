# Generation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the generation-only experiment pipeline that dispatches corpus items through generation conditions/tasks, records every job's status, and persists its output with full reproducibility provenance — the foundation the seven condition-specific backends (C1–C7) will be built on top of, one at a time, in later work.

**Architecture:** A YAML plan expands (via a hard-coded task/condition eligibility table) into `GenerationJob` rows, tracked in a SQLite registry (`experiments/runs/runs.db`). A bounded thread-pool runner claims `pending` jobs one at a time, dispatches each to a per-condition `GenerationBackend`, and writes its artifacts, raw trace, and metadata into `experiments/runs/<job_id>/`. Only the C1 (Full pipeline) backend is implemented now, wrapping `psalm_saga.agent.build_agent()` exactly as `psalm-saga-batch` already does; C2–C7 are registered as backends that raise `NotImplementedError` until built.

**Tech Stack:** Python 3.14, `psalm_saga` (existing package, in-process), `pandas`/`pyarrow` (reading `corpus.parquet`), `PyYAML` (plan files), stdlib `sqlite3` + `concurrent.futures.ThreadPoolExecutor`, `pytest` + `pytest`'s `tmp_path`/`monkeypatch` fixtures.

**Spec:** `docs/superpowers/specs/2026-09-22-generation-pipeline-design.md`

## Global Constraints

- In-process invocation only: condition backends that use the agent call `psalm_saga.agent.build_agent()` directly — no shelling out to `psalm-saga-batch` (spec §1, §5).
- Job identity `(plan_name, task, condition, item_id, generator_family, language, replicate, is_pilot)` hashes to a stable `job_id`; re-expanding a plan or re-running the pipeline must never duplicate a job (spec §2, §6).
- SQLite is the single source of truth for job status; heavy artifacts (trace, generated text) live on disk per job, not in the database (spec §6, §7).
- Bounded thread-pool concurrency (`--workers N`); no cross-worker rate limiter is added — each job's `build_agent()` call already carries `psalm_saga`'s own per-agent rate limiter/retry middleware (spec §8).
- Failed jobs never auto-retry; retrying is an explicit `retry --failed` command (spec §6, §8, §9).
- Only C1 is implemented; C2–C7 are registered stub backends that raise `NotImplementedError` naming the condition (spec §5).
- This plan does not implement the judging/instrument pipeline, any backend beyond C1, or authoring of premises/gold/scratch specifications — all separate follow-up work (spec §1, §12).

---

## File Structure

```
experiments/
  __init__.py
  pipeline/
    __init__.py
    models.py          # GenerationJob, GenerationResult, JobStatus/Task/Condition types
    plan.py             # Plan, TaskSpec, load_plan, TASK_CONDITION_ELIGIBILITY, expand_jobs
    resolver.py          # ResolvedInput, InputResolver, InputNotFoundError
    generators.py        # resolve_model (generator_family -> concrete model id)
    registry.py          # Registry (SQLite job table)
    runner.py            # run_job, run_pending (bounded worker pool)
    cli.py               # python -m experiments.pipeline.cli {expand,run,status,retry}
    backends/
      __init__.py        # BACKEND_REGISTRY
      base.py            # GenerationBackend protocol, NotImplementedBackend
      full_pipeline.py   # C1 — FullPipelineBackend
      no_review.py       # C2 — stub
      flat_with_spec.py  # C3 — stub
      no_spec.py         # C4 — stub
      flat.py            # C5 — stub
      agents_room.py     # C6 — stub
      human.py           # C7 — stub
  plans/
    pilot.yaml            # example plan for the manual smoke test
tests/
  experiments/
    __init__.py
    test_models.py
    test_plan.py
    test_resolver.py
    test_generators.py
    test_registry.py
    test_backends.py
    test_full_pipeline.py
    test_runner.py
    test_cli.py
```

---

### Task 1: Package scaffolding and the `GenerationJob` model

**Files:**
- Create: `experiments/__init__.py`
- Create: `experiments/pipeline/__init__.py`
- Create: `experiments/pipeline/models.py`
- Test: `tests/experiments/__init__.py`
- Test: `tests/experiments/test_models.py`

**Interfaces:**
- Produces: `Task = Literal["A", "B", "C", "D"]`, `Condition = Literal["C1"..."C7"]`, `JobStatus = Literal["pending", "running", "done", "failed", "abandoned"]`, `GenerationJob` (frozen dataclass, fields: `plan_name: str, task: Task, condition: Condition, item_id: str, generator_family: str, language: str, replicate: int = 0, is_pilot: bool = False`, property `job_id: str`), `GenerationResult` (frozen dataclass, fields: `artifacts: dict[str, str], trace: list[dict[str, Any]], config: dict[str, Any]`).

- [ ] **Step 1: Create empty package files**

```python
# experiments/__init__.py
"""Study-specific orchestration code for the PSALM-SAGA experiments.

Not an installed/versioned package like `psalm_saga` — run in-place via
`python -m experiments.pipeline.cli` from the repository root.
"""
```

```python
# experiments/pipeline/__init__.py
"""The generation pipeline: dispatches corpus items through generation
conditions/tasks and records what got produced, with full reproducibility
provenance. See `docs/superpowers/specs/2026-09-22-generation-pipeline-design.md`.
"""
```

```python
# tests/experiments/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/experiments/test_models.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/experiments/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.models'`

- [ ] **Step 4: Write the implementation**

```python
# experiments/pipeline/models.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/experiments/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add experiments/__init__.py experiments/pipeline/__init__.py experiments/pipeline/models.py tests/experiments/__init__.py tests/experiments/test_models.py
git commit -m "feat(experiments): add GenerationJob/GenerationResult data model"
```

---

### Task 2: Plan loading and job expansion

**Files:**
- Create: `experiments/pipeline/plan.py`
- Test: `tests/experiments/test_plan.py`
- Modify: `pyproject.toml` (add `pandas`, `pyarrow`, `pyyaml` to a new `experiments` dependency group)

**Interfaces:**
- Consumes: `experiments.pipeline.models.GenerationJob`, `Task`, `Condition` (Task 1).
- Produces: `TASK_CONDITION_ELIGIBILITY: dict[Task, frozenset[Condition]]`, `PlanError(ValueError)`, `TaskSpec` (frozen dataclass: `conditions: tuple[Condition, ...], generators: tuple[str, ...]`), `Plan` (frozen dataclass: `name: str, is_pilot: bool, corpus_filter: dict[str, Any], tasks: dict[Task, TaskSpec]`), `load_plan(path: Path) -> Plan`, `expand_jobs(plan: Plan, corpus: pd.DataFrame) -> list[GenerationJob]`.

- [ ] **Step 1: Add pandas/pyarrow/pyyaml as declared dependencies**

Run: `uv add --group experiments pandas pyarrow pyyaml`

This also fixes an existing gap: `experiments/build_corpus_dataset.py` already imports `pandas`/`pyarrow` but neither was ever declared in `pyproject.toml`, so a clean `uv sync` wouldn't have installed them.

- [ ] **Step 2: Write the failing tests**

```python
# tests/experiments/test_plan.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_plan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.plan'`

- [ ] **Step 4: Write the implementation**

```python
# experiments/pipeline/plan.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_plan.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add experiments/pipeline/plan.py tests/experiments/test_plan.py pyproject.toml uv.lock
git commit -m "feat(experiments): add plan loading and job expansion"
```

---

### Task 3: Input resolution

**Files:**
- Create: `experiments/pipeline/resolver.py`
- Test: `tests/experiments/test_resolver.py`

**Interfaces:**
- Consumes: `experiments.pipeline.models.GenerationJob` (Task 1).
- Produces: `InputKind = Literal["premise", "gold_spec", "scratch_spec", "source_text"]`, `ResolvedInput` (frozen dataclass: `kind: InputKind, content: str, source_path: Path`), `InputNotFoundError(FileNotFoundError)`, `InputResolver` (constructed with `data_dir: Path`, method `resolve(job: GenerationJob) -> ResolvedInput`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_resolver.py
"""Tests for `experiments.pipeline.resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiments.pipeline.models import GenerationJob
from experiments.pipeline.resolver import InputNotFoundError, InputResolver


def _job(task: str, item_id: str = "satire_the_happy_prince", language: str = "english") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task=task,  # type: ignore[arg-type]
        condition="C1",
        item_id=item_id,
        generator_family="frontier",
        language=language,
    )


def test_resolve_reads_premise_for_task_a(tmp_path: Path) -> None:
    premises = tmp_path / "premises"
    premises.mkdir()
    (premises / "satire_the_happy_prince.md").write_text("A statue learns to give.", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("A"))

    assert resolved.kind == "premise"
    assert resolved.content == "A statue learns to give."


def test_resolve_reads_gold_spec_for_task_b(tmp_path: Path) -> None:
    gold = tmp_path / "specs" / "gold"
    gold.mkdir(parents=True)
    (gold / "satire_the_happy_prince.md").write_text("# Gold spec", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("B"))

    assert resolved.kind == "gold_spec"
    assert resolved.content == "# Gold spec"


def test_resolve_reads_scratch_spec_for_task_d(tmp_path: Path) -> None:
    scratch = tmp_path / "specs" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "scratch_en_01.md").write_text("# Scratch spec", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("D", item_id="scratch_en_01"))

    assert resolved.kind == "scratch_spec"
    assert resolved.content == "# Scratch spec"


def test_resolve_reads_source_text_for_task_c(tmp_path: Path) -> None:
    stories = tmp_path / "stories" / "english"
    stories.mkdir(parents=True)
    (stories / "satire_the_happy_prince.txt").write_text("Once upon a time.", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("C"))

    assert resolved.kind == "source_text"
    assert resolved.content == "Once upon a time."


def test_resolve_raises_input_not_found_with_the_expected_path(tmp_path: Path) -> None:
    with pytest.raises(InputNotFoundError, match="satire_the_happy_prince"):
        InputResolver(tmp_path).resolve(_job("A"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.resolver'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/resolver.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_resolver.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/resolver.py tests/experiments/test_resolver.py
git commit -m "feat(experiments): add input resolution by data-directory convention"
```

---

### Task 4: Generator-family model resolution

**Files:**
- Create: `experiments/pipeline/generators.py`
- Test: `tests/experiments/test_generators.py`

**Interfaces:**
- Produces: `UnknownGeneratorFamilyError(KeyError)`, `resolve_model(generator_family: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_generators.py
"""Tests for `experiments.pipeline.generators`."""

from __future__ import annotations

import pytest

from experiments.pipeline.generators import UnknownGeneratorFamilyError, resolve_model


def test_resolve_model_returns_the_default_for_a_known_family() -> None:
    assert resolve_model("frontier") == "anthropic:claude-sonnet-4-6"


def test_resolve_model_raises_for_an_unknown_family() -> None:
    with pytest.raises(UnknownGeneratorFamilyError, match="unknown_family"):
        resolve_model("unknown_family")


def test_resolve_model_honors_an_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PSALM_SAGA_EXPERIMENTS_GENERATOR_FRONTIER", "anthropic:claude-opus-5")

    assert resolve_model("frontier") == "anthropic:claude-opus-5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_generators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.generators'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/generators.py
"""Maps a plan's symbolic generator-family names to concrete model identifiers.

Kept separate from `psalm_saga.settings.Settings` since a plan's generator
families (e.g. "frontier", "open_weight") are a pipeline-level concept
spanning every backend, not a single `psalm_saga` agent setting.
"""

from __future__ import annotations

import os

_DEFAULT_MODELS: dict[str, str] = {
    "frontier": "anthropic:claude-sonnet-4-6",
    "open_weight": "openai:gpt-oss-120b",
}

_ENV_OVERRIDE_PREFIX = "PSALM_SAGA_EXPERIMENTS_GENERATOR_"


class UnknownGeneratorFamilyError(KeyError):
    """Raised when a job names a generator family with no configured model."""


def resolve_model(generator_family: str) -> str:
    """Resolve a plan's `generator_family` name to a concrete model identifier.

    Checks `PSALM_SAGA_EXPERIMENTS_GENERATOR_<FAMILY>` (uppercased) first,
    then the built-in defaults, so a family's model can be repointed per
    machine or run without editing code.
    """
    env_key = f"{_ENV_OVERRIDE_PREFIX}{generator_family.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    try:
        return _DEFAULT_MODELS[generator_family]
    except KeyError as exc:
        raise UnknownGeneratorFamilyError(
            f"No model configured for generator family {generator_family!r}. "
            f"Known families: {sorted(_DEFAULT_MODELS)}"
        ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_generators.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/generators.py tests/experiments/test_generators.py
git commit -m "feat(experiments): add generator-family to model-id resolution"
```

---

### Task 5: Job registry

**Files:**
- Create: `experiments/pipeline/registry.py`
- Test: `tests/experiments/test_registry.py`

**Interfaces:**
- Consumes: `experiments.pipeline.models.GenerationJob`, `JobStatus` (Task 1).
- Produces: `JobRecord` (frozen dataclass: `job: GenerationJob, status: JobStatus, output_dir: str | None, error: str | None, config: dict[str, Any] | None`), `Registry` (constructed with `db_path: Path`; methods `close() -> None`, `insert_jobs(jobs: list[GenerationJob]) -> int`, `claim_next_pending(plan_name: str) -> GenerationJob | None`, `mark_done(job_id: str, *, output_dir: str, config: dict[str, Any]) -> None`, `mark_failed(job_id: str, *, error: str) -> None`, `status_counts(plan_name: str) -> dict[str, int]`, `requeue_failed(plan_name: str) -> int`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_registry.py
"""Tests for `experiments.pipeline.registry`."""

from __future__ import annotations

from pathlib import Path

from experiments.pipeline.models import GenerationJob
from experiments.pipeline.registry import Registry


def _job(item_id: str, condition: str = "C1") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task="A",
        condition=condition,  # type: ignore[arg-type]
        item_id=item_id,
        generator_family="frontier",
        language="english",
    )


def test_insert_jobs_is_idempotent(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    jobs = [_job("a"), _job("b")]

    first = registry.insert_jobs(jobs)
    second = registry.insert_jobs(jobs)

    assert first == 2
    assert second == 0
    assert registry.status_counts("pilot") == {"pending": 2}
    registry.close()


def test_claim_next_pending_marks_it_running_and_returns_the_job(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])

    claimed = registry.claim_next_pending("pilot")

    assert claimed is not None
    assert claimed.item_id == "a"
    assert registry.status_counts("pilot") == {"running": 1}
    registry.close()


def test_claim_next_pending_returns_none_once_exhausted(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    registry.claim_next_pending("pilot")

    assert registry.claim_next_pending("pilot") is None
    registry.close()


def test_successive_claims_never_return_the_same_job(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b")])

    first = registry.claim_next_pending("pilot")
    second = registry.claim_next_pending("pilot")

    assert first is not None
    assert second is not None
    assert first.item_id != second.item_id
    registry.close()


def test_mark_done_records_status_output_dir_and_config(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    job = registry.claim_next_pending("pilot")
    assert job is not None

    registry.mark_done(job.job_id, output_dir="/runs/abc123", config={"model": "x"})

    assert registry.status_counts("pilot") == {"done": 1}
    registry.close()


def test_mark_failed_records_status_and_error(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    job = registry.claim_next_pending("pilot")
    assert job is not None

    registry.mark_failed(job.job_id, error="boom")

    assert registry.status_counts("pilot") == {"failed": 1}
    registry.close()


def test_requeue_failed_resets_failed_jobs_to_pending(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b")])
    first = registry.claim_next_pending("pilot")
    assert first is not None
    registry.mark_failed(first.job_id, error="boom")

    requeued = registry.requeue_failed("pilot")

    assert requeued == 1
    assert registry.status_counts("pilot") == {"pending": 2}
    registry.close()


def test_registry_persists_across_reconnects(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    Registry(db_path).insert_jobs([_job("a")])

    reopened = Registry(db_path)
    assert reopened.status_counts("pilot") == {"pending": 1}
    reopened.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.registry'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/registry.py
"""SQLite-backed job registry: the single source of truth for job status.

Every public method acquires `self._lock` for its whole body, so this
registry is safe to share across a `ThreadPoolExecutor`'s worker threads —
see spec §6, §8. That single lock is sufficient here: the worker pool this
registry serves is bounded and small, so simple serialization beats the
complexity of finer-grained SQLite transaction tuning.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiments.pipeline.models import GenerationJob, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL,
    task TEXT NOT NULL,
    condition TEXT NOT NULL,
    item_id TEXT NOT NULL,
    generator_family TEXT NOT NULL,
    language TEXT NOT NULL,
    replicate INTEGER NOT NULL,
    is_pilot INTEGER NOT NULL,
    status TEXT NOT NULL,
    output_dir TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    config_json TEXT
);
"""

_SELECT_COLUMNS = (
    "job_id, plan_name, task, condition, item_id, generator_family, "
    "language, replicate, is_pilot, status, output_dir, error, "
    "started_at, finished_at, config_json"
)


@dataclass(frozen=True)
class JobRecord:
    """One `jobs` row, read back out as a `GenerationJob` plus its status fields."""

    job: GenerationJob
    status: JobStatus
    output_dir: str | None
    error: str | None
    config: dict[str, Any] | None


def _row_to_record(row: tuple[Any, ...]) -> JobRecord:
    """Reconstruct a `JobRecord` from one raw `jobs` row (column order: `_SELECT_COLUMNS`)."""
    (
        _job_id, plan_name, task, condition, item_id, generator_family,
        language, replicate, is_pilot, status, output_dir, error,
        _started_at, _finished_at, config_json,
    ) = row
    job = GenerationJob(
        plan_name=plan_name, task=task, condition=condition, item_id=item_id,
        generator_family=generator_family, language=language,
        replicate=replicate, is_pilot=bool(is_pilot),
    )
    return JobRecord(
        job=job, status=status, output_dir=output_dir, error=error,
        config=json.loads(config_json) if config_json else None,
    )


class Registry:
    """Wraps one `runs.db` SQLite connection, guarded by a single lock."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def insert_jobs(self, jobs: list[GenerationJob]) -> int:
        """Insert every job not already present by `job_id`. Returns the count newly inserted."""
        with self._lock:
            inserted = 0
            for job in jobs:
                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs
                        (job_id, plan_name, task, condition, item_id, generator_family,
                         language, replicate, is_pilot, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        job.job_id, job.plan_name, job.task, job.condition, job.item_id,
                        job.generator_family, job.language, job.replicate, int(job.is_pilot),
                    ),
                )
                inserted += cursor.rowcount
            self._conn.commit()
            return inserted

    def claim_next_pending(self, plan_name: str) -> GenerationJob | None:
        """Atomically claim one `pending` job for `plan_name`, marking it `running`.

        Returns `None` once no `pending` job remains for this plan.
        """
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM jobs WHERE plan_name = ? AND status = 'pending' LIMIT 1",
                (plan_name,),
            ).fetchone()
            if row is None:
                return None
            record = _row_to_record(row)
            self._conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                (datetime.now(UTC).isoformat(), record.job.job_id),
            )
            self._conn.commit()
            return record.job

    def mark_done(self, job_id: str, *, output_dir: str, config: dict[str, Any]) -> None:
        """Record a job's successful completion."""
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'done', output_dir = ?, config_json = ?, "
                "finished_at = ? WHERE job_id = ?",
                (output_dir, json.dumps(config), datetime.now(UTC).isoformat(), job_id),
            )
            self._conn.commit()

    def mark_failed(self, job_id: str, *, error: str) -> None:
        """Record a job's failure. Does not auto-retry — see `requeue_failed`."""
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE job_id = ?",
                (error, datetime.now(UTC).isoformat(), job_id),
            )
            self._conn.commit()

    def status_counts(self, plan_name: str) -> dict[str, int]:
        """Count jobs for `plan_name` by status."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM jobs WHERE plan_name = ? GROUP BY status",
                (plan_name,),
            ).fetchall()
            return dict(rows)

    def requeue_failed(self, plan_name: str) -> int:
        """Reset every `failed` job for `plan_name` back to `pending`. Returns the count changed."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE jobs SET status = 'pending', error = NULL "
                "WHERE plan_name = ? AND status = 'failed'",
                (plan_name,),
            )
            self._conn.commit()
            return cursor.rowcount
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_registry.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/registry.py tests/experiments/test_registry.py
git commit -m "feat(experiments): add SQLite job registry"
```

---

### Task 6: Backend protocol and C2–C7 stubs

**Files:**
- Create: `experiments/pipeline/backends/__init__.py`
- Create: `experiments/pipeline/backends/base.py`
- Create: `experiments/pipeline/backends/no_review.py`
- Create: `experiments/pipeline/backends/flat_with_spec.py`
- Create: `experiments/pipeline/backends/no_spec.py`
- Create: `experiments/pipeline/backends/flat.py`
- Create: `experiments/pipeline/backends/agents_room.py`
- Create: `experiments/pipeline/backends/human.py`
- Test: `tests/experiments/test_backends.py`

**Interfaces:**
- Consumes: `experiments.pipeline.models.{Condition, GenerationJob, GenerationResult}` (Task 1), `experiments.pipeline.resolver.ResolvedInput` (Task 3).
- Produces: `GenerationBackend` (Protocol: `run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult`), `NotImplementedBackend` (class, constructed with `condition: Condition`), each stub module exporting `BACKEND: NotImplementedBackend`. `experiments.pipeline.backends.BACKEND_REGISTRY: dict[Condition, GenerationBackend]` — **note:** this task leaves `"C1"` unset; Task 7 adds it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_backends.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_backends.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.backends'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/backends/base.py
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
```

```python
# experiments/pipeline/backends/no_review.py
"""Stub backend for C2 (No Review) — not yet implemented.

See spec §5: C2–C7 are stubs so the runner/registry/storage design is
proven end-to-end against C1 before each remaining condition is built as
its own follow-up task.
"""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C2")
```

```python
# experiments/pipeline/backends/flat_with_spec.py
"""Stub backend for C3 (Flat+Spec) — not yet implemented. See `no_review.py`."""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C3")
```

```python
# experiments/pipeline/backends/no_spec.py
"""Stub backend for C4 (No Spec) — not yet implemented. See `no_review.py`."""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C4")
```

```python
# experiments/pipeline/backends/flat.py
"""Stub backend for C5 (Flat) — not yet implemented. See `no_review.py`."""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C5")
```

```python
# experiments/pipeline/backends/agents_room.py
"""Stub backend for C6 (Agents' Room) — not yet implemented. See `no_review.py`."""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C6")
```

```python
# experiments/pipeline/backends/human.py
"""Stub backend for C7 (Human) — not yet implemented. See `no_review.py`."""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C7")
```

```python
# experiments/pipeline/backends/__init__.py
"""Maps each of the seven generation conditions to its backend."""

from __future__ import annotations

from experiments.pipeline.backends import agents_room, flat, flat_with_spec, human, no_review, no_spec
from experiments.pipeline.backends.base import GenerationBackend
from experiments.pipeline.models import Condition

BACKEND_REGISTRY: dict[Condition, GenerationBackend] = {
    "C2": no_review.BACKEND,
    "C3": flat_with_spec.BACKEND,
    "C4": no_spec.BACKEND,
    "C5": flat.BACKEND,
    "C6": agents_room.BACKEND,
    "C7": human.BACKEND,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_backends.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/backends/ tests/experiments/test_backends.py
git commit -m "feat(experiments): add backend protocol and C2-C7 stub backends"
```

---

### Task 7: C1 (Full pipeline) backend

**Files:**
- Create: `experiments/pipeline/backends/full_pipeline.py`
- Modify: `experiments/pipeline/backends/__init__.py`
- Test: `tests/experiments/test_full_pipeline.py`

**Interfaces:**
- Consumes: `experiments.pipeline.models.{GenerationJob, GenerationResult}` (Task 1), `experiments.pipeline.resolver.ResolvedInput` (Task 3), `experiments.pipeline.generators.resolve_model` (Task 4), `psalm_saga.agent.{build_agent, open_sqlite_checkpointer}`, `psalm_saga.bootstrap.BATCH_BOOTSTRAP_SKILL`, `psalm_saga.session.{generate_session_id, session_directory}`, `psalm_saga.settings.Settings`.
- Produces: `FullPipelineBackend` (class, method `run(job, input_ref) -> GenerationResult`), module-level `BACKEND = FullPipelineBackend()`. `experiments.pipeline.backends.BACKEND_REGISTRY["C1"]` now set.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_full_pipeline.py
"""Tests for `experiments.pipeline.backends.full_pipeline` (C1).

Mirrors the mocking pattern `tests/unit/test_batch_cli.py` uses for
`psalm_saga.batch_cli`: `build_agent`/`open_sqlite_checkpointer` are
monkeypatched so no live model call happens, and the fake agent writes
files into the session's real `docs/` directory to simulate what the
skills would have produced.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from experiments.pipeline.backends import full_pipeline
from experiments.pipeline.models import GenerationJob
from experiments.pipeline.resolver import ResolvedInput
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeAgent:
    def __init__(self, docs_dir: Path, docs_to_write: dict[str, str]) -> None:
        self._docs_dir = docs_dir
        self._docs_to_write = docs_to_write

    def invoke(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        for rel_path, content in self._docs_to_write.items():
            target = self._docs_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return {"messages": [_FakeMessage(payload["messages"][0]["content"]), _FakeMessage("done")]}


@contextmanager
def _fake_checkpointer(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    yield None


def _job(task: str = "A") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task=task,  # type: ignore[arg-type]
        condition="C1",
        item_id="satire_the_happy_prince",
        generator_family="frontier",
        language="english",
    )


def test_run_writes_docs_dir_contents_as_artifacts_and_records_the_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    fixed_session_id = "session-fixed"
    docs_dir = session_directory(settings, fixed_session_id) / "docs"

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: fixed_session_id)
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline,
        "build_agent",
        lambda *_a, **_kw: _FakeAgent(docs_dir, {"drafts/story/story-spec.md": "# Spec"}),
    )

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="A statue learns to give.", source_path=tmp_path)

    result = backend.run(_job(), input_ref)

    assert result.artifacts == {"drafts/story/story-spec.md": "# Spec"}
    assert len(result.trace) == 2
    assert result.trace[0]["content"] == "A statue learns to give."
    assert result.trace[1]["content"] == "done"


def test_run_resolves_generator_family_and_records_the_model_id_in_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(full_pipeline, "build_agent", lambda *_a, **_kw: _FakeAgent(docs_dir, {}))

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)

    result = backend.run(_job(), input_ref)

    assert result.config["orchestration_model_name"] == "anthropic:claude-sonnet-4-6"
    assert result.config["subagent_model_name"] == "anthropic:claude-sonnet-4-6"
    assert result.config["task"] == "A"
    assert result.config["condition"] == "C1"


def test_run_uses_the_batch_bootstrap_skill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_args: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent(docs_dir, {})

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(full_pipeline, "build_agent", fake_build_agent)

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)

    backend.run(_job(), input_ref)

    assert captured_kwargs["bootstrap_skill"] == full_pipeline.BATCH_BOOTSTRAP_SKILL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_full_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.backends.full_pipeline'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/backends/full_pipeline.py
"""C1 (Full pipeline) backend: spec -> plan -> draft -> review -> repair,
via `psalm_saga`'s own `build_agent()`, one session per job.

Follows the same invocation shape `psalm_saga.batch_cli.run_batch` already
uses for `psalm-saga-batch`, but one job = one independent session (not
one session generating many stories) — see spec §5.
"""

from __future__ import annotations

from psalm_saga.agent import build_agent, open_sqlite_checkpointer
from psalm_saga.bootstrap import BATCH_BOOTSTRAP_SKILL
from psalm_saga.session import generate_session_id, session_directory
from psalm_saga.settings import Settings

from experiments.pipeline.generators import resolve_model
from experiments.pipeline.models import GenerationJob, GenerationResult
from experiments.pipeline.resolver import ResolvedInput

_TASK_INSTRUCTIONS: dict[str, str] = {
    "A": "Generate a complete story from this premise, using the batch-story-generation skill:\n\n{content}",
    "B": (
        "Generate a complete story that instantiates this specification exactly. "
        "The specification below is already final — do not re-elicit it, only carry "
        "it into a plan and drafted chapters. Use the batch-story-generation skill:\n\n{content}"
    ),
    "C": (
        "Extract a dimension specification from this source story, then produce six "
        "variants — one per dimension — each regenerating exactly one dimension and "
        "locking the other five. Use the batch-story-generation skill:\n\n{content}"
    ),
}


class FullPipelineBackend:
    """Runs one job through the full `psalm_saga` agent pipeline (C1)."""

    def run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult:
        settings = Settings()
        model_id = resolve_model(job.generator_family)
        settings.agent.orchestration_model_name = model_id
        settings.agent.subagent_model_name = model_id

        session_id = generate_session_id()
        instruction = _TASK_INSTRUCTIONS[job.task].format(content=input_ref.content)

        with open_sqlite_checkpointer(settings, session_id) as checkpointer:
            agent = build_agent(
                settings,
                session_id=session_id,
                checkpointer=checkpointer,
                bootstrap_skill=BATCH_BOOTSTRAP_SKILL,
            )
            result = agent.invoke(
                {"messages": [{"role": "user", "content": instruction}]},
                config={"configurable": {"thread_id": session_id}},
            )
            trace = [
                {"type": message.__class__.__name__, "content": getattr(message, "content", "")}
                for message in result["messages"]
            ]
            artifacts = self._collect_artifacts(settings, session_id)

        return GenerationResult(
            artifacts=artifacts,
            trace=trace,
            config={
                "orchestration_model_name": settings.agent.orchestration_model_name,
                "subagent_model_name": settings.agent.subagent_model_name,
                "psalm_saga_session_id": session_id,
                "task": job.task,
                "condition": job.condition,
            },
        )

    def _collect_artifacts(self, settings: Settings, session_id: str) -> dict[str, str]:
        """Read every file this session's `docs/` tree produced, keyed by relative path."""
        docs_dir = session_directory(settings, session_id) / "docs"
        if not docs_dir.is_dir():
            return {}
        return {
            str(path.relative_to(docs_dir)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in sorted(docs_dir.rglob("*"))
            if path.is_file()
        }


BACKEND = FullPipelineBackend()
```

- [ ] **Step 4: Wire C1 into `BACKEND_REGISTRY`**

```python
# experiments/pipeline/backends/__init__.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_full_pipeline.py tests/experiments/test_backends.py -v`
Expected: PASS (all tests, including a new implicit check that `BACKEND_REGISTRY["C1"]` is a `FullPipelineBackend`)

- [ ] **Step 6: Commit**

```bash
git add experiments/pipeline/backends/full_pipeline.py experiments/pipeline/backends/__init__.py tests/experiments/test_full_pipeline.py
git commit -m "feat(experiments): add C1 full-pipeline backend"
```

---

### Task 8: Runner (bounded worker pool)

**Files:**
- Create: `experiments/pipeline/runner.py`
- Test: `tests/experiments/test_runner.py`

**Interfaces:**
- Consumes: `experiments.pipeline.backends.BACKEND_REGISTRY` (Tasks 6–7), `experiments.pipeline.models.GenerationJob` (Task 1), `experiments.pipeline.registry.Registry` (Task 5), `experiments.pipeline.resolver.InputResolver` (Task 3).
- Produces: `run_job(job: GenerationJob, resolver: InputResolver, runs_dir: Path) -> tuple[str, dict[str, Any]]`, `run_pending(registry: Registry, plan_name: str, resolver: InputResolver, runs_dir: Path, workers: int) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_runner.py
"""Tests for `experiments.pipeline.runner`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.pipeline import runner
from experiments.pipeline.models import GenerationJob, GenerationResult
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver


def _job(item_id: str = "a") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task="A",
        condition="C1",
        item_id=item_id,
        generator_family="frontier",
        language="english",
    )


class _FakeBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def run(self, job: GenerationJob, input_ref) -> GenerationResult:  # noqa: ANN001
        if self._fail:
            raise RuntimeError("simulated backend failure")
        return GenerationResult(
            artifacts={"story.md": f"# Story for {job.item_id}\n\nfrom: {input_ref.content}"},
            trace=[{"type": "AIMessage", "content": "ok"}],
            config={"model": "fake-model"},
        )


def _resolver(tmp_path: Path, *, item_ids: list[str]) -> InputResolver:
    premises = tmp_path / "data" / "premises"
    premises.mkdir(parents=True)
    for item_id in item_ids:
        (premises / f"{item_id}.md").write_text(f"premise for {item_id}", encoding="utf-8")
    return InputResolver(tmp_path / "data")


def test_run_job_persists_artifacts_trace_and_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    resolver = _resolver(tmp_path, item_ids=["a"])
    runs_dir = tmp_path / "runs"
    job = _job("a")

    output_dir, config = runner.run_job(job, resolver, runs_dir)

    output_path = Path(output_dir)
    assert (output_path / "story.md").read_text(encoding="utf-8") == (
        "# Story for a\n\nfrom: premise for a"
    )
    trace = (output_path / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(trace[0]) == {"type": "AIMessage", "content": "ok"}
    metadata = json.loads((output_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["job_id"] == job.job_id
    assert metadata["item_id"] == "a"
    assert config == {"model": "fake-model"}


def test_run_pending_processes_every_job_with_bounded_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b"), _job("c")])
    resolver = _resolver(tmp_path, item_ids=["a", "b", "c"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=2)

    assert registry.status_counts("pilot") == {"done": 3}
    registry.close()


def test_run_pending_marks_a_failing_job_failed_without_stopping_the_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend(fail=True))
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b")])
    resolver = _resolver(tmp_path, item_ids=["a", "b"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=2)

    assert registry.status_counts("pilot") == {"failed": 2}
    registry.close()


def test_run_pending_reports_missing_input_as_a_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("missing-premise")])
    resolver = _resolver(tmp_path, item_ids=[])  # no premise files written

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1)

    assert registry.status_counts("pilot") == {"failed": 1}
    registry.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.runner'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/runner.py
"""Bounded worker pool: claims pending jobs, dispatches to backends, records results.

See spec §8.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from experiments.pipeline.backends import BACKEND_REGISTRY
from experiments.pipeline.models import GenerationJob
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver

logger = logging.getLogger(__name__)


def run_job(job: GenerationJob, resolver: InputResolver, runs_dir: Path) -> tuple[str, dict[str, Any]]:
    """Run one job through its backend and persist its output.

    Returns `(output_dir, config)` on success. Raises on any failure — a
    missing input, a backend not yet implemented, or a model-call error
    all surface the same way here; the caller (`run_pending`'s worker
    loop) is responsible for catching and recording it against the
    registry. Keeping this function ignorant of the registry keeps it
    independently testable.
    """
    backend = BACKEND_REGISTRY[job.condition]
    input_ref = resolver.resolve(job)
    result = backend.run(job, input_ref)

    output_dir = runs_dir / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in result.artifacts.items():
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    trace_lines = "\n".join(json.dumps(entry) for entry in result.trace)
    (output_dir / "trace.jsonl").write_text(
        f"{trace_lines}\n" if result.trace else "", encoding="utf-8"
    )

    metadata = {
        "job_id": job.job_id,
        "plan_name": job.plan_name,
        "task": job.task,
        "condition": job.condition,
        "item_id": job.item_id,
        "generator_family": job.generator_family,
        "language": job.language,
        "replicate": job.replicate,
        "is_pilot": job.is_pilot,
        "config": result.config,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return str(output_dir), result.config


def run_pending(
    registry: Registry, plan_name: str, resolver: InputResolver, runs_dir: Path, workers: int
) -> None:
    """Run every `pending` job for `plan_name`, `workers` at a time.

    Each worker claims one job, runs it, and records the outcome, looping
    until no `pending` jobs remain. A job's own exception — including a
    missing input or an unimplemented backend — is caught and recorded as
    `failed`; it never stops the pool or other in-flight jobs.
    """

    def _worker_loop() -> None:
        while True:
            job = registry.claim_next_pending(plan_name)
            if job is None:
                return
            try:
                output_dir, config = run_job(job, resolver, runs_dir)
            except Exception as exc:  # noqa: BLE001 — one bad job must never stop the pool
                registry.mark_failed(job.job_id, error=str(exc))
                logger.warning("Job %s failed: %s", job.job_id, exc)
            else:
                registry.mark_done(job.job_id, output_dir=output_dir, config=config)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_worker_loop) for _ in range(workers)]
        for future in futures:
            future.result()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_runner.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/runner.py tests/experiments/test_runner.py
git commit -m "feat(experiments): add bounded worker-pool runner"
```

---

### Task 9: CLI

**Files:**
- Create: `experiments/pipeline/cli.py`
- Test: `tests/experiments/test_cli.py`

**Interfaces:**
- Consumes: `experiments.pipeline.plan.{load_plan, expand_jobs}` (Task 2), `experiments.pipeline.registry.Registry` (Task 5), `experiments.pipeline.resolver.InputResolver` (Task 3), `experiments.pipeline.runner.run_pending` (Task 8).
- Produces: `main(argv: list[str] | None = None) -> None`, plus internal `_parse_args`, `_cmd_expand`, `_cmd_run`, `_cmd_status`, `_cmd_retry`, `print_status`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_cli.py
"""Tests for `experiments.pipeline.cli`."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from experiments.pipeline import cli
from experiments.pipeline.registry import Registry


def _write_corpus(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.parquet"
    pd.DataFrame(
        [
            {"id": "satire_a", "language": "english"},
            {"id": "gothic_a", "language": "dutch"},
        ]
    ).to_parquet(path)
    return path


def _write_plan(tmp_path: Path) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(
        yaml.safe_dump(
            {"name": "pilot", "tasks": {"A": {"conditions": ["C1"], "generators": ["frontier"]}}}
        ),
        encoding="utf-8",
    )
    return path


def test_expand_command_inserts_jobs_into_the_registry(tmp_path: Path) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)
    runs_dir = tmp_path / "runs"

    cli.main(["expand", "--plan", str(plan_path), "--corpus", str(corpus_path), "--runs-dir", str(runs_dir)])

    registry = Registry(runs_dir / "runs.db")
    assert registry.status_counts("pilot") == {"pending": 2}
    registry.close()


def test_expand_command_is_idempotent(tmp_path: Path) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)
    runs_dir = tmp_path / "runs"
    args = ["expand", "--plan", str(plan_path), "--corpus", str(corpus_path), "--runs-dir", str(runs_dir)]

    cli.main(args)
    cli.main(args)

    registry = Registry(runs_dir / "runs.db")
    assert registry.status_counts("pilot") == {"pending": 2}
    registry.close()


def test_run_command_expands_then_delegates_to_run_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)
    runs_dir = tmp_path / "runs"
    captured: dict[str, Any] = {}

    def fake_run_pending(registry, plan_name, resolver, run_dir, workers) -> None:  # noqa: ANN001
        captured["plan_name"] = plan_name
        captured["run_dir"] = run_dir
        captured["workers"] = workers

    monkeypatch.setattr(cli, "run_pending", fake_run_pending)

    cli.main(
        ["run", "--plan", str(plan_path), "--corpus", str(corpus_path), "--runs-dir", str(runs_dir), "--workers", "3"]
    )

    assert captured["plan_name"] == "pilot"
    assert captured["run_dir"] == runs_dir
    assert captured["workers"] == 3


def test_status_command_prints_counts_by_status(tmp_path: Path) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)
    runs_dir = tmp_path / "runs"
    cli.main(["expand", "--plan", str(plan_path), "--corpus", str(corpus_path), "--runs-dir", str(runs_dir)])

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        cli.main(["status", "--plan-name", "pilot", "--runs-dir", str(runs_dir)])

    assert "pending: 2" in buffer.getvalue()


def test_retry_command_requeues_failed_jobs(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    registry = Registry(runs_dir / "runs.db")
    from experiments.pipeline.models import GenerationJob

    job = GenerationJob(
        plan_name="pilot", task="A", condition="C1", item_id="a",
        generator_family="frontier", language="english",
    )
    registry.insert_jobs([job])
    registry.claim_next_pending("pilot")
    registry.mark_failed(job.job_id, error="boom")
    registry.close()

    cli.main(["retry", "--failed", "--plan-name", "pilot", "--runs-dir", str(runs_dir)])

    registry = Registry(runs_dir / "runs.db")
    assert registry.status_counts("pilot") == {"pending": 1}
    registry.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/experiments/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiments.pipeline.cli'`

- [ ] **Step 3: Write the implementation**

```python
# experiments/pipeline/cli.py
"""Command-line entry point: `python -m experiments.pipeline.cli <command> ...`. See spec §9."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from experiments.pipeline.plan import expand_jobs, load_plan
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver
from experiments.pipeline.runner import run_pending

DEFAULT_CORPUS_PATH = Path("experiments/data/stories/corpus.parquet")
DEFAULT_DATA_DIR = Path("experiments/data")
DEFAULT_RUNS_DIR = Path("experiments/runs")


def _load_corpus(corpus_path: Path) -> pd.DataFrame:
    return pd.read_parquet(corpus_path)


def _cmd_expand(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    corpus = _load_corpus(args.corpus)
    jobs = expand_jobs(plan, corpus)
    registry = Registry(args.runs_dir / "runs.db")
    try:
        inserted = registry.insert_jobs(jobs)
        print(f"Plan {plan.name!r}: {len(jobs)} jobs described, {inserted} newly inserted.")
    finally:
        registry.close()


def _cmd_run(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    corpus = _load_corpus(args.corpus)
    registry = Registry(args.runs_dir / "runs.db")
    try:
        registry.insert_jobs(expand_jobs(plan, corpus))
        resolver = InputResolver(args.data_dir)
        run_pending(registry, plan.name, resolver, args.runs_dir, workers=args.workers)
        print_status(registry, plan.name)
    finally:
        registry.close()


def _cmd_status(args: argparse.Namespace) -> None:
    registry = Registry(args.runs_dir / "runs.db")
    try:
        print_status(registry, args.plan_name)
    finally:
        registry.close()


def print_status(registry: Registry, plan_name: str) -> None:
    """Print job counts by status for `plan_name`."""
    counts = registry.status_counts(plan_name)
    print(f"Plan {plan_name!r}:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")


def _cmd_retry(args: argparse.Namespace) -> None:
    registry = Registry(args.runs_dir / "runs.db")
    try:
        n = registry.requeue_failed(args.plan_name)
        print(f"Requeued {n} failed job(s) for plan {args.plan_name!r}.")
    finally:
        registry.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    common.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    common.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)

    parser = argparse.ArgumentParser(
        prog="experiments.pipeline", description="Generation pipeline for the PSALM-SAGA experiments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    expand_parser = subparsers.add_parser("expand", parents=[common])
    expand_parser.add_argument("--plan", type=Path, required=True)
    expand_parser.set_defaults(func=_cmd_expand)

    run_parser = subparsers.add_parser("run", parents=[common])
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--workers", type=int, default=1)
    run_parser.set_defaults(func=_cmd_run)

    status_parser = subparsers.add_parser("status", parents=[common])
    status_parser.add_argument("--plan-name", required=True)
    status_parser.set_defaults(func=_cmd_status)

    retry_parser = subparsers.add_parser("retry", parents=[common])
    retry_parser.add_argument("--failed", action="store_true", required=True)
    retry_parser.add_argument("--plan-name", required=True)
    retry_parser.set_defaults(func=_cmd_retry)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for `python -m experiments.pipeline.cli`."""
    args = _parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/experiments/test_cli.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add experiments/pipeline/cli.py tests/experiments/test_cli.py
git commit -m "feat(experiments): add pipeline CLI (expand/run/status/retry)"
```

---

### Task 10: Example plan, `.gitignore`, and full-suite verification

**Files:**
- Create: `experiments/plans/pilot.yaml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: everything from Tasks 1–9. No new interfaces produced — this task is wiring and verification only.

- [ ] **Step 1: Add the example pilot plan**

```yaml
# experiments/plans/pilot.yaml
name: pilot
is_pilot: true
corpus_filter:
  sample_per_language: 1
tasks:
  A:
    conditions: [C1]
    generators: [frontier]
```

This is deliberately the smallest possible plan (1 item per language, 1 condition, 1 generator) — its purpose is the manual smoke test below, not pilot-scale coverage.

- [ ] **Step 2: Ignore generated run artifacts**

Add to `.gitignore`, near the existing `experiments/data/stories/` entry:

```gitignore
experiments/runs/
```

Run: `git diff .gitignore` to confirm only that line was added.

- [ ] **Step 3: Run the full new test suite**

Run: `uv run pytest tests/experiments -v`
Expected: PASS (every test from Tasks 1–9)

- [ ] **Step 4: Run ruff over the new package**

Run: `uv run ruff check experiments/`
Expected: no errors. If ruff flags something (e.g. an import order or missing docstring), fix it in place — do not add `# noqa` suppressions for a real finding.

- [ ] **Step 5: Run the full existing test suite to confirm nothing else broke**

Run: `uv run pytest -v`
Expected: PASS (all `tests/unit/` tests plus the new `tests/experiments/` tests)

- [ ] **Step 6: Manual smoke test against a real corpus item (requires a model provider API key)**

This step is not automated — it validates the path automated tests mock out (a real `build_agent()` call). Skip it if no provider credentials are available in this environment; note that in the task's completion report rather than silently skipping.

```bash
mkdir -p experiments/data/premises
echo "A city statue quietly gives away its own gold leaf to the poor, one winter at a time, until a swallow who was supposed to have flown south stays to help and dies of cold at its feet." > experiments/data/premises/satire_the_happy_prince.md

uv run python -m experiments.pipeline.cli run --plan experiments/plans/pilot.yaml --workers 1
uv run python -m experiments.pipeline.cli status --plan-name pilot
```

Expected: the plan expands to 1 job (Task A, C1, `satire_the_happy_prince`, `frontier`, English — the Dutch item is skipped because no premise file exists for it, and that job will show as `failed` with an `InputNotFoundError` message, not crash the run). Inspect `experiments/runs/<job_id>/` for `metadata.json`, `trace.jsonl`, and the story files the agent produced.

- [ ] **Step 7: Commit**

```bash
git add experiments/plans/pilot.yaml .gitignore
git commit -m "feat(experiments): add example pilot plan and ignore run artifacts"
```

---

## Self-Review Notes

- **Spec coverage:** §2 (job model) → Task 1. §3 (plan/expansion) → Task 2. §4 (input resolution) → Task 3. §5 (backends, C1) → Tasks 6–7 (generator-model resolution, needed for §11's exact-model-identifier requirement, added as Task 4). §6 (registry) → Task 5. §7 (storage layout) → `runner.run_job` in Task 8. §8 (runner) → Task 8. §9 (CLI) → Task 9. §10 (package location) → file structure throughout. §12 (out of scope) → respected; no task implements C2–C7, judging, or content authoring.
- **Placeholder scan:** none found — every step has complete code, no "TBD"/"add error handling" placeholders.
- **Type consistency:** `GenerationJob`, `GenerationResult`, `ResolvedInput`, `Registry`, `BACKEND_REGISTRY`, `run_job`/`run_pending` signatures are used identically across every task that consumes them, cross-checked against each task's "Consumes" list.
