# Experiment Run Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make experiment runs match each source's length, show progress while they run, allow running a single corpus item, and treat abandoned stories as a recorded outcome that restarts from scratch.

**Architecture:** Each job gets a length range at expansion time (from the corpus `word_count`, or a plan-level override) and stores it in the registry. The C1 backend streams the agent run, reports stage changes through a progress sink, and runs up to three story attempts, each in a fresh session, recording a `attempts.jsonl` timeline. The runner reports job start and finish lines, marks abandoned jobs separately from failures, and the CLI filters pending jobs by corpus id.

**Tech Stack:** Python 3.14, SQLite (`sqlite3`), pandas/pyarrow (corpus), PyYAML (plans), `psalm_saga` (`story_length`, `batch_session`, `agent`, `session`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-experiment-run-improvements-design.md`

**Deviations from the spec (flagged):**
- `fix_loop_activated` records the review cycle number and review file path, not the failing dimensions. The failing dimensions are only known from the reviewer's text, so they are recorded in the abandonment reason from `ABANDONED.md`.
- Commits are not part of this plan. Run `git add`/`git commit` only when you ask.

## Global Constraints

- Python 3.14; ruff `line-length = 100`; tests run with `.venv/Scripts/python.exe -m pytest tests/experiments -q`.
- No changes under `psalm_saga/` (skills, settings, or helpers are only imported).
- `GenerationJob.job_id` identity fields are unchanged, so existing `runs.db` rows and job folders stay valid.
- Live model calls cost money. Only Task 8 makes one, and only after you approve it.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `experiments/pipeline/models.py` | Modify | `GenerationJob.length_range` (non-identity); `JobAbandoned` exception |
| `experiments/pipeline/registry.py` | Modify | `length_range` column + migration; `abandoned` status; item filter; `count_pending`; `mark_abandoned`; retry covers abandoned |
| `experiments/pipeline/length.py` | Create | ±10% band from `word_count`; directive rendering |
| `experiments/pipeline/plan.py` | Modify | `Plan.length` override; sets `length_range` on expansion |
| `experiments/pipeline/progress.py` | Create | `ProgressSink`, `JobProgress` (console + `progress.log`), tool-call → stage mapping |
| `experiments/pipeline/backends/base.py` | Modify | Protocol takes `progress`; stub passes it through |
| `experiments/pipeline/backends/full_pipeline.py` | Modify | Streaming, length directive, attempt loop, abandonment |
| `experiments/pipeline/runner.py` | Modify | Job start/finish lines, `JobAbandoned` handling, persistence helper, item filter |
| `experiments/pipeline/cli.py` | Modify | `run --item` (repeatable) with validation |
| `tests/experiments/test_registry_run_improvements.py` | Create | Registry changes |
| `tests/experiments/test_length.py` | Create | Band and directive |
| `tests/experiments/test_plan_length.py` | Create | Plan override and expansion |
| `tests/experiments/test_progress.py` | Create | Stage mapping and `JobProgress` |
| `tests/experiments/test_full_pipeline.py` | Modify | Stream-based fake agent; new cases |
| `tests/experiments/test_runner.py` | Modify | Progress sink, abandoned path, item filter |
| `tests/experiments/test_cli.py` | Modify | `--item` |
| `docs/EXPERIMENTS.md` | Modify | Document `--item`, progress, length, abandonment |

---

### Task 1: Registry: length column, abandoned status, item filter

**Files:**
- Modify: `experiments/pipeline/models.py`
- Modify: `experiments/pipeline/registry.py`
- Test: `tests/experiments/test_registry_run_improvements.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `GenerationJob.length_range: str | None = None` (not part of `job_id`).
  - `JobAbandoned(reason: str, artifacts: dict[str, str], trace: list[dict[str, Any]], config: dict[str, Any])` in `models.py`.
  - `Registry.claim_next_pending(plan_name: str, item_ids: Collection[str] | None = None) -> GenerationJob | None`
  - `Registry.count_pending(plan_name: str, item_ids: Collection[str] | None = None) -> int`
  - `Registry.mark_abandoned(job_id: str, *, reason: str, config: dict[str, Any]) -> None`
  - `Registry.requeue_failed(plan_name)` now also requeues `abandoned` jobs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_registry_run_improvements.py
from __future__ import annotations

import sqlite3
from pathlib import Path

from experiments.pipeline.models import GenerationJob
from experiments.pipeline.registry import Registry


def _job(item_id: str, length_range: str | None = "270-330") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot", task="A", condition="C1", item_id=item_id,
        generator_family="frontier", language="english", length_range=length_range,
    )


def test_length_range_is_not_part_of_job_identity() -> None:
    assert _job("a", "270-330").job_id == _job("a", "100-120").job_id


def test_length_range_round_trips_through_the_registry(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a", "270-330")])
    claimed = registry.claim_next_pending("pilot")
    assert claimed is not None
    assert claimed.length_range == "270-330"
    registry.close()


def test_claim_respects_item_filter_and_skips_done_jobs(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b")])
    first = registry.claim_next_pending("pilot", item_ids={"b"})
    assert first is not None and first.item_id == "b"
    registry.mark_done(first.job_id, output_dir="x", config={})
    assert registry.claim_next_pending("pilot", item_ids={"b"}) is None
    assert registry.count_pending("pilot") == 1
    registry.close()


def test_mark_abandoned_sets_status_and_reason(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    job = _job("a")
    registry.insert_jobs([job])
    registry.claim_next_pending("pilot")
    registry.mark_abandoned(job.job_id, reason="fix-loop cap reached", config={"attempts": 3})
    assert registry.status_counts("pilot") == {"abandoned": 1}
    registry.close()


def test_requeue_failed_also_requeues_abandoned(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "runs.db")
    job = _job("a")
    registry.insert_jobs([job])
    registry.claim_next_pending("pilot")
    registry.mark_abandoned(job.job_id, reason="cap", config={})
    assert registry.requeue_failed("pilot") == 1
    assert registry.status_counts("pilot") == {"pending": 1}
    registry.close()


def test_opening_an_old_database_adds_the_length_column(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    old = sqlite3.connect(db)
    old.execute(
        "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, plan_name TEXT NOT NULL, task TEXT NOT NULL, "
        "condition TEXT NOT NULL, item_id TEXT NOT NULL, generator_family TEXT NOT NULL, "
        "language TEXT NOT NULL, replicate INTEGER NOT NULL, is_pilot INTEGER NOT NULL, "
        "status TEXT NOT NULL, output_dir TEXT, error TEXT, started_at TEXT, finished_at TEXT, "
        "config_json TEXT)"
    )
    old.commit()
    old.close()
    Registry(db).close()
    columns = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(jobs)")}
    assert "length_range" in columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_registry_run_improvements.py -q`
Expected: FAIL (`length_range` is not a field; `count_pending`/`mark_abandoned` do not exist).

- [ ] **Step 3: Implement models changes**

In `experiments/pipeline/models.py`, add a field to `GenerationJob` after `is_pilot` (leave `job_id` untouched):

```python
    is_pilot: bool = False
    length_range: str | None = None
    """Word-count range (`MIN-MAX`) the story should land in. Not part of identity."""
```

Append to `models.py`:

```python
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
```

- [ ] **Step 4: Implement registry changes**

In `experiments/pipeline/registry.py`:

1. Add `length_range TEXT` to `_SCHEMA` (after `config_json TEXT`).
2. Add a migration helper and call it in `__init__` right after `CREATE TABLE`:

```python
def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    """Add `column` to `table` if an older database predates it."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
```

In `__init__`:

```python
        with self._lock:
            self._conn.execute(_SCHEMA)
            _ensure_column(self._conn, "jobs", "length_range", "TEXT")
            self._conn.commit()
```

3. Add `length_range` to `_SELECT_COLUMNS` (append `, length_range`), unpack it in `_row_to_record` (`length_range` is the last column) and pass `length_range=length_range` into `GenerationJob(...)`.

4. In `insert_jobs`, add `length_range` to the column list and the values (`job.length_range`).

5. Replace `claim_next_pending` and add `count_pending`:

```python
    def _pending_filter(
        self, plan_name: str, item_ids: Collection[str] | None
    ) -> tuple[str, list[Any]] | None:
        """WHERE clause for pending jobs of `plan_name`, optionally limited to `item_ids`.

        Returns None when `item_ids` is empty, meaning nothing can match.
        """
        clause = "plan_name = ? AND status = 'pending'"
        params: list[Any] = [plan_name]
        if item_ids is not None:
            ids = sorted(item_ids)
            if not ids:
                return None
            clause += f" AND item_id IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        return clause, params

    def claim_next_pending(
        self, plan_name: str, item_ids: Collection[str] | None = None
    ) -> GenerationJob | None:
        """Atomically claim one `pending` job for `plan_name`, marking it `running`.

        `item_ids` limits the claim to jobs whose `item_id` is listed. Returns
        `None` once no matching `pending` job remains.
        """
        with self._lock:
            filtered = self._pending_filter(plan_name, item_ids)
            if filtered is None:
                return None
            clause, params = filtered
            row = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM jobs WHERE {clause} LIMIT 1",  # noqa: S608 (_SELECT_COLUMNS is a constant, values are parameterized)
                params,
            ).fetchone()
            if row is None:
                return None
            stored_job_id = row[0]
            record = _row_to_record(row)
            cursor = self._conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? "
                "WHERE job_id = ? AND status = 'pending'",
                (datetime.now(UTC).isoformat(), stored_job_id),
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                return None
            return record.job

    def count_pending(self, plan_name: str, item_ids: Collection[str] | None = None) -> int:
        """Count `pending` jobs for `plan_name`, optionally limited to `item_ids`."""
        with self._lock:
            filtered = self._pending_filter(plan_name, item_ids)
            if filtered is None:
                return 0
            clause, params = filtered
            row = self._conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause}", params).fetchone()  # noqa: S608
            return int(row[0])
```

6. Add `mark_abandoned` after `mark_failed`:

```python
    def mark_abandoned(self, job_id: str, *, reason: str, config: dict[str, Any]) -> None:
        """Record that every story attempt for a job was abandoned, with the reason."""
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'abandoned', error = ?, config_json = ?, "
                "finished_at = ? WHERE job_id = ?",
                (reason, json.dumps(config), datetime.now(UTC).isoformat(), job_id),
            )
            self._conn.commit()
```

7. In `requeue_failed`, change the `WHERE` to `plan_name = ? AND status IN ('failed', 'abandoned')`.

Add `from collections.abc import Collection` to the imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments -q`
Expected: PASS for the new file. Existing tests in `tests/experiments/test_registry.py` and `test_runner.py` still pass.

---

### Task 2: Length band and plan override

**Files:**
- Create: `experiments/pipeline/length.py`
- Modify: `experiments/pipeline/plan.py`
- Test: `tests/experiments/test_length.py`, `tests/experiments/test_plan_length.py`

**Interfaces:**
- Consumes: `GenerationJob.length_range` (Task 1).
- Produces:
  - `band_for_word_count(word_count: int, band: float = 0.10) -> str` (e.g. `300` → `"270-330"`).
  - `directive_for(length_range: str) -> str` (a sentence for the model's instruction, from `psalm_saga.story_length`).
  - `Plan.length: str | None`. `load_plan` reads the optional top-level `length:` key and validates it.
  - `expand_jobs(plan, corpus)` sets `length_range` on every job: `plan.length` if set, else the band from the row's `word_count`. Raises `PlanError` if neither is available.

- [ ] **Step 1: Write the failing tests**

```python
# tests/experiments/test_length.py
from __future__ import annotations

import pytest

from experiments.pipeline.length import band_for_word_count, directive_for


def test_band_is_plus_minus_ten_percent_of_the_source_word_count() -> None:
    assert band_for_word_count(300) == "270-330"


def test_band_never_goes_below_one_word() -> None:
    assert band_for_word_count(1) == "1-1"


def test_directive_names_the_word_range() -> None:
    directive = directive_for("270-330")
    assert "270" in directive and "330" in directive
```

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_length.py tests/experiments/test_plan_length.py -q`
Expected: FAIL (`experiments.pipeline.length` does not exist; `Plan` has no `length`).

- [ ] **Step 3: Implement `length.py`**

```python
"""Per-item word-count bands for experiment jobs.

See the design spec §1. The band comes from the corpus `word_count`, and the
rendering reuses `psalm_saga.story_length` so the directive matches what the
interactive and batch CLIs send.
"""

from __future__ import annotations

from psalm_saga.story_length import format_length_directive, parse_chapters, parse_length

DEFAULT_BAND = 0.10


def band_for_word_count(word_count: int, band: float = DEFAULT_BAND) -> str:
    """Return the `MIN-MAX` range `±band` around `word_count`, never below 1 word."""
    if word_count < 1:
        raise ValueError(f"word_count must be at least 1, got {word_count}")
    low = max(1, round(word_count * (1 - band)))
    high = max(low, round(word_count * (1 + band)))
    return f"{low}-{high}"


def directive_for(length_range: str) -> str:
    """Render the story-length directive for a `MIN-MAX` range, with chapters on auto."""
    return format_length_directive(parse_length(length_range), parse_chapters(None))
```

- [ ] **Step 4: Implement the plan changes**

In `experiments/pipeline/plan.py`:

1. Add the import `from experiments.pipeline.length import band_for_word_count` and `from psalm_saga.story_length import parse_length`.
2. Add a field to `Plan`: `length: str | None = None` (after `tasks`).
3. In `load_plan`, before `return Plan(...)`:

```python
    length = raw.get("length")
    if length is not None:
        length = str(length)
        try:
            parse_length(length)
        except ValueError as exc:
            raise PlanError(f"invalid plan length {length!r}: {exc}") from exc
```

and pass `length=length` into `Plan(...)`.

4. In `expand_jobs`, compute the length once per row. Replace the inner loop body's `GenerationJob(...)` call so it includes `length_range=`, computed like this:

```python
    for _, row in filtered.iterrows():
        length_range = _length_range_for(plan, row)
        for task, task_spec in plan.tasks.items():
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
                            length_range=length_range,
                        )
                    )
```

(Move the `for _, row in filtered.iterrows():` loop outside the `for task` loop, so the length is computed once per row. Keep the job order identical to the current code: outer loop over tasks, then rows. Use this order: `for task, task_spec in plan.tasks.items(): for _, row in filtered.iterrows(): length_range = ...`. Do not change order, so existing tests stay stable.)

5. Add the helper:

```python
def _length_range_for(plan: Plan, row: pd.Series) -> str:
    """The plan's `length` if set, else the band from the item's `word_count`."""
    if plan.length is not None:
        return plan.length
    if "word_count" not in row or pd.isna(row["word_count"]):
        raise PlanError(
            f"item {row['id']!r} has no word_count and the plan sets no `length`"
        )
    return band_for_word_count(int(row["word_count"]))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments -q`
Expected: PASS. `tests/experiments/test_plan.py` still passes (job order unchanged).

---

### Task 3: Progress sink and stage detection

**Files:**
- Create: `experiments/pipeline/progress.py`
- Test: `tests/experiments/test_progress.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ProgressSink(Protocol)` with `def stage(self, label: str) -> None`.
  - `class NullProgress` (no-op sink, used by tests and direct backend calls).
  - `class JobProgress(prefix: str, log_path: Path)` prints `"{prefix} {label}"` and appends the same line to `log_path`.
  - `tool_calls_from_update(payload: Any) -> list[tuple[str, dict[str, Any]]]`
  - `stage_for_tool_call(name: str, args: dict[str, Any]) -> str | None`

- [ ] **Step 1: Confirm the tool names**

The stage mapping depends on the tool names deepagents uses for file writes and sub-agent dispatch. Verify them before writing code:

Run: `.venv/Scripts/python.exe -c "import deepagents, pathlib; print(pathlib.Path(deepagents.__file__).parent)"` and then `Grep` that directory for `"write_file"`, `"edit_file"`, and `"task"` as tool names.

Expected: the three names exist. If a name differs, use the name the package actually registers and update the constants in Step 3.

- [ ] **Step 2: Write the failing tests**

```python
# tests/experiments/test_progress.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.pipeline.progress import (
    JobProgress,
    stage_for_tool_call,
    tool_calls_from_update,
)


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("write_file", {"file_path": "drafts/story/story-spec.md"}, "spec"),
        ("write_file", {"file_path": "drafts/story/story-plan.md"}, "plan"),
        ("write_file", {"file_path": "drafts/story/chapter-2-title.md"}, "chapter 2"),
        ("write_file", {"file_path": "drafts/story/story-review.md"}, "review"),
        ("write_file", {"file_path": "drafts/story/ABANDONED.md"}, "abandoned"),
        ("edit_file", {"file_path": "drafts/story/chapter-1-title.md"}, "chapter 1"),
        ("task", {"subagent_type": "chapter-writer"}, "draft"),
        ("task", {"subagent_type": "dimension-reviewer"}, "review"),
        ("read_file", {"file_path": "anything.md"}, None),
    ],
)
def test_stage_for_tool_call(name: str, args: dict, expected: str | None) -> None:
    assert stage_for_tool_call(name, args) == expected


def test_tool_calls_are_extracted_from_an_updates_payload() -> None:
    message = SimpleNamespace(tool_calls=[{"name": "task", "args": {"subagent_type": "chapter-writer"}}])
    payload = {"model": {"messages": [message]}}
    assert tool_calls_from_update(payload) == [("task", {"subagent_type": "chapter-writer"})]


def test_job_progress_prints_and_appends_to_the_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "progress.log"
    progress = JobProgress(prefix="[1/2] story_a", log_path=log)
    progress.stage("spec")
    progress.stage("draft ch 2/5")
    assert "[1/2] story_a spec" in capsys.readouterr().out
    assert log.read_text(encoding="utf-8").splitlines() == [
        "[1/2] story_a spec",
        "[1/2] story_a draft ch 2/5",
    ]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_progress.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 4: Implement `progress.py`**

```python
"""Progress reporting for generation jobs.

See the design spec §2. The backend reports stage changes through a
`ProgressSink`; the runner supplies a `JobProgress` that prints to the console
and appends to the job's `progress.log`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

_CHAPTER_RE = re.compile(r"chapter-(\d+)-")
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


class ProgressSink(Protocol):
    def stage(self, label: str) -> None: ...


class NullProgress:
    """A sink that ignores every stage. Used when no one is watching."""

    def stage(self, label: str) -> None:
        return None


class JobProgress:
    """Prints each stage line and appends it to the job's `progress.log`."""

    def __init__(self, prefix: str, log_path: Path) -> None:
        self._prefix = prefix
        self._log_path = log_path

    def stage(self, label: str) -> None:
        line = f"{self._prefix} {label}"
        print(line, flush=True)  # noqa: T201 — operator-facing progress output
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def stage_for_tool_call(name: str, args: dict[str, Any]) -> str | None:
    """Map one tool call to a human-readable stage, or None if it is not a stage change."""
    if name == "task":
        subagent = args.get("subagent_type")
        if subagent == "chapter-writer":
            return "draft"
        if subagent == "dimension-reviewer":
            return "review"
        return None
    if name in _WRITE_TOOLS:
        path = str(args.get("file_path", ""))
        if path.endswith("ABANDONED.md"):
            return "abandoned"
        if path.endswith("DONE.md"):
            return "done"
        if path.endswith("-spec.md"):
            return "spec"
        if path.endswith("-plan.md"):
            return "plan"
        if path.endswith("-review.md"):
            return "review"
        match = _CHAPTER_RE.search(path)
        if match:
            return f"chapter {match.group(1)}"
    return None


def tool_calls_from_update(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    """Extract `(name, args)` for every tool call in one `updates`-mode stream payload."""
    calls: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(payload, dict):
        return calls
    for node_update in payload.values():
        if not isinstance(node_update, dict):
            continue
        for message in node_update.get("messages", []) or []:
            for call in getattr(message, "tool_calls", None) or []:
                calls.append((call["name"], dict(call.get("args") or {})))
    return calls
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_progress.py -q`
Expected: PASS.

---

### Task 4: Backend: stream the run and report stages

**Files:**
- Modify: `experiments/pipeline/backends/base.py`
- Modify: `experiments/pipeline/backends/full_pipeline.py`
- Modify: `tests/experiments/test_full_pipeline.py`

**Interfaces:**
- Consumes: `ProgressSink`, `tool_calls_from_update`, `stage_for_tool_call` (Task 3).
- Produces:
  - `GenerationBackend.run(job, input_ref, progress: ProgressSink) -> GenerationResult`.
  - `NotImplementedBackend.run(job, input_ref, progress)` (signature only; still raises).
  - `FullPipelineBackend.run(job, input_ref, progress)` streams with `agent.stream(..., stream_mode=["messages", "updates"])`, the same call shape as `psalm_saga/batch_cli.py`.
  - `result.trace` starts with `{"type": "HumanMessage", "content": <instruction>}`, followed by one entry per AI or tool message seen in the stream.

- [ ] **Step 1: Update the fake agent and write the failing test**

Replace `_FakeAgent` in `tests/experiments/test_full_pipeline.py` with a streaming fake. The fake writes the files, then yields updates in the same shape as the real stream:

```python
class _FakeAI:
    def __init__(self, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeAgent:
    def __init__(self, docs_dir: Path, docs_to_write: dict[str, str]) -> None:
        self._docs_dir = docs_dir
        self._docs_to_write = docs_to_write

    def stream(self, payload: dict[str, Any], **_kwargs: Any) -> Iterator[tuple[str, Any]]:
        for rel_path, content in self._docs_to_write.items():
            target = self._docs_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            yield ("updates", {"model": {"messages": [_FakeAI(tool_calls=[
                {"name": "write_file", "args": {"file_path": rel_path}}
            ])]}})
        yield ("updates", {"model": {"messages": [_FakeAI(content="done")]}})
```

Update the existing tests that reference `invoke` or `trace` shape:
- `test_run_writes_docs_dir_contents_as_artifacts_and_records_the_trace`: trace now has the instruction first, then the tool-call and `done` entries. Assert `len(result.trace) >= 2`, `result.trace[0]["type"] == "HumanMessage"`, `"A statue learns to give." in result.trace[0]["content"]`, and `result.trace[-1]["content"] == "done"`.
- `test_run_handles_task_d_...`: assert `"# Scratch spec content" in result.trace[0]["content"]`.

Add:

```python
def test_run_reports_stage_changes_from_the_stream(monkeypatch, tmp_path) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    stages: list[str] = []

    class _Sink:
        def stage(self, label: str) -> None:
            stages.append(label)

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _FakeAgent(docs_dir, dict(_FINISHED_DRAFT))
    )

    full_pipeline.FullPipelineBackend().run(
        _job(), ResolvedInput(kind="premise", content="premise", source_path=tmp_path), _Sink()
    )

    assert "plan" in stages
    assert "done" in stages
```

Note `_FINISHED_DRAFT` writes `drafts/story/DONE.md`, so `done` appears. Every existing `backend.run(_job(), input_ref)` call gains a third argument, `NullProgress()`. Add `from experiments.pipeline.progress import NullProgress` at the top and pass it in each existing call.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q`
Expected: FAIL (`run()` takes 3 positional arguments but 4 were given; the fake's `invoke` is no longer used).

- [ ] **Step 3: Implement**

`experiments/pipeline/backends/base.py`:

```python
from experiments.pipeline.progress import ProgressSink
...
class GenerationBackend(Protocol):
    def run(
        self, job: GenerationJob, input_ref: ResolvedInput, progress: ProgressSink
    ) -> GenerationResult: ...


class NotImplementedBackend:
    ...
    def run(
        self, job: GenerationJob, input_ref: ResolvedInput, progress: ProgressSink
    ) -> GenerationResult:
        raise NotImplementedError(f"{self._condition} backend is not yet implemented")
```

`experiments/pipeline/backends/full_pipeline.py`: replace the `agent.invoke` block with a streaming helper. Add imports `from experiments.pipeline.progress import ProgressSink, stage_for_tool_call, tool_calls_from_update`.

```python
    def run(
        self, job: GenerationJob, input_ref: ResolvedInput, progress: ProgressSink
    ) -> GenerationResult:
        settings = Settings()
        model_id = resolve_model(job.generator_family)
        settings.agent.orchestration_model_name = model_id
        settings.agent.subagent_model_name = model_id

        session_id = generate_session_id()
        instruction_template = _TASK_INSTRUCTIONS[job.task]
        instruction = instruction_template.format(content=input_ref.content)

        with open_sqlite_checkpointer(settings, session_id) as checkpointer:
            agent = build_agent(
                settings,
                session_id=session_id,
                checkpointer=checkpointer,
                bootstrap_skill=BATCH_BOOTSTRAP_SKILL,
            )
            trace = [{"type": "HumanMessage", "content": instruction}]
            for entry in self._stream_run(agent, session_id, instruction, progress):
                trace.append(entry)
            promoted = self._promote_finished_drafts(settings, session_id)
            if not promoted:
                raise RuntimeError(
                    f"No story was completed for job {job.job_id}: no draft under this "
                    "session carries a DONE.md marker and none was abandoned."
                )
            artifacts = self._collect_artifacts(settings, session_id)

        return GenerationResult(artifacts=artifacts, trace=trace, config={...})  # unchanged keys

    def _stream_run(
        self, agent: Any, session_id: str, instruction: str, progress: ProgressSink
    ) -> Iterator[dict[str, Any]]:
        """Run the agent, reporting stage changes and yielding one trace entry per message."""
        for mode, payload in agent.stream(
            {"messages": [{"role": "user", "content": instruction}]},
            config={"configurable": {"thread_id": session_id}},
            stream_mode=["messages", "updates"],
        ):
            if mode != "updates":
                continue
            for node_update in (payload.values() if isinstance(payload, dict) else []):
                if not isinstance(node_update, dict):
                    continue
                for message in node_update.get("messages", []) or []:
                    yield {"type": message.__class__.__name__, "content": getattr(message, "content", "")}
            for name, args in tool_calls_from_update(payload):
                stage = stage_for_tool_call(name, args)
                if stage is not None:
                    progress.stage(stage)
```

Add `from collections.abc import Iterator` and `from typing import Any`.

Note: `mode == "messages"` payloads are token chunks; they are skipped, so the trace keeps one entry per whole message, as before. Import `Any` for the helper.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q`
Expected: PASS.

---

### Task 5: Backend: length directive and realised word count

**Files:**
- Modify: `experiments/pipeline/backends/full_pipeline.py`
- Modify: `tests/experiments/test_full_pipeline.py`

**Interfaces:**
- Consumes: `directive_for` (Task 2); `GenerationJob.length_range` (Task 1).
- Produces:
  - The instruction sent to the agent is `directive + "\n\n" + template` when `job.length_range` is set, and unchanged otherwise.
  - `config["length_range"]` (the range or `None`) and `config["realised_words"]` (word count of the promoted story, or `None`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/experiments/test_full_pipeline.py`:

```python
def test_run_prepends_the_length_directive_when_a_range_is_set(monkeypatch, tmp_path) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    captured: dict[str, Any] = {}

    class _Capture(_FakeAgent):
        def stream(self, payload, **kwargs):
            captured["instruction"] = payload["messages"][0]["content"]
            return super().stream(payload, **kwargs)

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _Capture(docs_dir, dict(_FINISHED_DRAFT))
    )

    job = GenerationJob(
        plan_name="pilot", task="A", condition="C1", item_id="satire_the_happy_prince",
        generator_family="frontier", language="english", length_range="270-330",
    )
    result = full_pipeline.FullPipelineBackend().run(
        job, ResolvedInput(kind="premise", content="premise text", source_path=tmp_path), NullProgress()
    )

    assert "270" in captured["instruction"] and "330" in captured["instruction"]
    assert result.config["length_range"] == "270-330"
    assert result.config["realised_words"] == len("Once upon a time.".split())
```

`_FINISHED_DRAFT`'s chapter text is `"# Chapter 1: Only\n\nOnce upon a time."`; `realised_words` counts the words in the promoted `stories/story.md`, which includes the title line. Compute it from the artifact instead of hardcoding: replace the last assert with `assert result.config["realised_words"] == len(result.artifacts["stories/story.md"].split())`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q -k length`
Expected: FAIL (no directive in the instruction; `length_range` missing from config).

- [ ] **Step 3: Implement**

In `full_pipeline.py`:

```python
from experiments.pipeline.length import directive_for
...
        instruction = instruction_template.format(content=input_ref.content)
        if job.length_range is not None:
            instruction = f"{directive_for(job.length_range)}\n\n{instruction}"
```

Keep the `prompt_template_sha256` computed from `instruction_template`, so it still identifies the template. Add to the `config` dict:

```python
                "length_range": job.length_range,
                "realised_words": _realised_words(artifacts, promoted),
```

with:

```python
def _realised_words(artifacts: dict[str, str], promoted: list[str]) -> int | None:
    """Word count of the first promoted story, or None when nothing was promoted."""
    if not promoted:
        return None
    text = artifacts.get(f"stories/{promoted[0]}.md")
    return len(text.split()) if text is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q`
Expected: PASS.

---

### Task 6: Backend: attempt loop and abandonment

**Files:**
- Modify: `experiments/pipeline/backends/full_pipeline.py`
- Modify: `tests/experiments/test_full_pipeline.py`

**Interfaces:**
- Consumes: `JobAbandoned` (Task 1); `ProgressSink` (Task 3); `psalm_saga.batch_session.drafts_dir`.
- Produces:
  - `MAX_STORY_ATTEMPTS = 3`.
  - `FullPipelineBackend.run` makes up to three attempts. Each uses a new session id and checkpointer, and a `stage("attempt n/3")` line is emitted.
  - An attempt is **abandoned** when a draft directory contains `ABANDONED.md` and no story is promoted. Its reason is that file's text. It is **successful** when a story is promoted.
  - Success: returns a `GenerationResult`. Top-level artifacts are the winning attempt's docs. Every attempt's docs are under `attempts/<n>/`.
  - All attempts abandoned: raises `JobAbandoned(reason=<last attempt's reason>, artifacts=<all attempts>, trace=<all attempts>, config=...)`.
  - An attempt that promotes nothing and leaves no `ABANDONED.md` raises `RuntimeError` naming the real cause.
  - `artifacts["attempts.jsonl"]` is the timeline: `attempt_started`, `fix_loop_activated`, `attempt_abandoned`, `attempt_done`, each with a UTC `at` timestamp.
  - `trace` entries carry `"attempt": n`.

- [ ] **Step 1: Write the failing tests**

```python
def _abandoned_draft(reason: str) -> dict[str, str]:
    return {
        "drafts/story/story-plan.md": "# Story — Story Plan\n",
        "drafts/story/story-review.md": "Partial",
        "drafts/story/ABANDONED.md": reason,
    }


def _run_with_attempt_sequence(monkeypatch, tmp_path, drafts_per_attempt):
    settings = Settings()
    settings.backend.root_dir = tmp_path
    sessions = iter(f"session-{i}" for i in range(1, 10))
    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: next(sessions))
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)

    attempts = iter(drafts_per_attempt)

    def fake_build_agent(_settings, *, session_id, **_kw):
        docs_dir = session_directory(settings, session_id) / "docs"
        return _FakeAgent(docs_dir, next(attempts))

    monkeypatch.setattr(full_pipeline, "build_agent", fake_build_agent)
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)
    return full_pipeline.FullPipelineBackend().run(_job(), input_ref, NullProgress())


def test_an_abandoned_attempt_is_retried_from_scratch_and_can_succeed(monkeypatch, tmp_path) -> None:
    result = _run_with_attempt_sequence(
        monkeypatch, tmp_path,
        [_abandoned_draft("cap reached once"), dict(_FINISHED_DRAFT)],
    )
    assert result.config["promoted_stories"] == ["story"]
    timeline = [json.loads(line)["event"] for line in result.artifacts["attempts.jsonl"].splitlines()]
    assert timeline.count("attempt_started") == 2
    assert "attempt_abandoned" in timeline and "attempt_done" in timeline
    assert "attempts/1/drafts/story/ABANDONED.md" in result.artifacts


def test_three_abandoned_attempts_raise_job_abandoned_with_the_reason(monkeypatch, tmp_path) -> None:
    reason = "Abandoned after three chapter review attempts: Character still Partial."
    with pytest.raises(JobAbandoned) as info:
        _run_with_attempt_sequence(monkeypatch, tmp_path, [_abandoned_draft(reason)] * 3)
    assert info.value.reason == reason
    assert "attempts/3/drafts/story/ABANDONED.md" in info.value.artifacts
    assert info.value.config["attempts"] == 3


def test_no_done_and_no_abandoned_marker_is_a_failure_not_an_abandonment(monkeypatch, tmp_path) -> None:
    with pytest.raises(RuntimeError, match="none was abandoned"):
        _run_with_attempt_sequence(
            monkeypatch, tmp_path, [{"drafts/story/story-plan.md": "# plan\n"}]
        )
```

Add imports: `import json`, `from experiments.pipeline.models import GenerationJob, JobAbandoned`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q -k "attempt or abandon or marker"`
Expected: FAIL (no attempt loop; `JobAbandoned` not raised).

- [ ] **Step 3: Implement**

Add to `full_pipeline.py`:

```python
MAX_STORY_ATTEMPTS = 3
"""Story attempts per job. Matches the per-chapter fix-loop cap in `reviewing-story-dimensions`."""
```

Replace `run` with the attempt loop. Helpers keep the `_promote_finished_drafts` and `_collect_artifacts` behaviour:

```python
    def run(
        self, job: GenerationJob, input_ref: ResolvedInput, progress: ProgressSink
    ) -> GenerationResult:
        settings = Settings()
        model_id = resolve_model(job.generator_family)
        settings.agent.orchestration_model_name = model_id
        settings.agent.subagent_model_name = model_id

        instruction_template = _TASK_INSTRUCTIONS[job.task]
        instruction = instruction_template.format(content=input_ref.content)
        if job.length_range is not None:
            instruction = f"{directive_for(job.length_range)}\n\n{instruction}"

        timeline: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        all_artifacts: dict[str, str] = {}
        last_reason = ""
        winner: tuple[int, str, list[str]] | None = None

        for attempt in range(1, MAX_STORY_ATTEMPTS + 1):
            progress.stage(f"attempt {attempt}/{MAX_STORY_ATTEMPTS}")
            outcome = self._run_attempt(settings, instruction, attempt, progress, timeline)
            trace.extend({**entry, "attempt": attempt} for entry in outcome.trace)
            all_artifacts.update(
                {f"attempts/{attempt}/{path}": text for path, text in outcome.artifacts.items()}
            )
            if outcome.promoted:
                winner = (attempt, outcome.session_id, outcome.promoted)
                timeline.append(_event("attempt_done", attempt, promoted=outcome.promoted))
                break
            last_reason = outcome.abandoned_reason
            timeline.append(_event("attempt_abandoned", attempt, reason=last_reason))

        all_artifacts["attempts.jsonl"] = "".join(json.dumps(e) + "\n" for e in timeline)
        config = {
            "orchestration_model_name": settings.agent.orchestration_model_name,
            "subagent_model_name": settings.agent.subagent_model_name,
            "model_kwargs": settings.agent.model_kwargs,
            "subagent_model_kwargs": settings.agent.subagent_model_kwargs,
            "task": job.task,
            "condition": job.condition,
            "length_range": job.length_range,
            "attempts": len([e for e in timeline if e["event"] == "attempt_started"]),
            "prompt_template_sha256": hashlib.sha256(instruction_template.encode("utf-8")).hexdigest(),
        }
        if winner is None:
            raise JobAbandoned(last_reason, artifacts=all_artifacts, trace=trace, config=config)

        attempt_no, session_id, promoted = winner
        winning_docs = self._collect_artifacts(settings, session_id)
        artifacts = {**winning_docs, **all_artifacts}
        config.update(
            {
                "psalm_saga_session_id": session_id,
                "promoted_stories": promoted,
                "winning_attempt": attempt_no,
                "realised_words": _realised_words(winning_docs, promoted),
            }
        )
        return GenerationResult(artifacts=artifacts, trace=trace, config=config)
```

`_run_attempt` returns an `_AttemptOutcome` dataclass (`session_id`, `promoted`, `abandoned_reason`, `artifacts`, `trace`). It:
1. Calls `generate_session_id()`, opens the checkpointer with `open_sqlite_checkpointer(settings, session_id)`, and calls `build_agent(...)` with `bootstrap_skill=BATCH_BOOTSTRAP_SKILL`.
2. Records `_event("attempt_started", attempt, session_id=session_id)` into `timeline`.
3. Streams with `_stream_run(agent, session_id, instruction, progress)`, counting writes to `*-review.md` in the stream. The first review is normal. From the second review on, append `_event("fix_loop_activated", attempt, cycle=n, review_file=path)` to `timeline` and call `progress.stage(f"fix attempt {n}")`. To get the path, change `_stream_run` to yield `("trace", entry)` and `("tool", (name, args))` items, so `_run_attempt` can see the tool calls as well as the trace entries.
4. After the stream, promotes finished drafts with `_promote_finished_drafts(settings, session_id)`.
5. If nothing was promoted, looks for `ABANDONED.md` under `drafts_dir(settings, session_id)/*/`. If found, `abandoned_reason` is its stripped text and the attempt records `_event("attempt_abandoned", ...)` (the caller records it too; do not duplicate it: the caller in step 3 above is the only place that appends `attempt_abandoned`, so remove the `timeline.append` there if you add it here). Otherwise raise `RuntimeError(f"No story was completed for job ...: no draft under this session carries a DONE.md marker and none was abandoned.")`.
6. Collects its artifacts with `_collect_artifacts(settings, session_id)` and its trace.

Implementation guidance for steps 4–5: keep `attempt_abandoned` in `run` only (as written above), and have `_run_attempt` just return the reason.

Add the module-level helper:

```python
def _event(name: str, attempt: int, **fields: Any) -> dict[str, Any]:
    """One `attempts.jsonl` line: event name, attempt number, UTC timestamp, extra fields."""
    return {
        "event": name,
        "attempt": attempt,
        "at": datetime.now(UTC).isoformat(),
        **fields,
    }
```

Add imports: `json`, `from dataclasses import dataclass`, `from datetime import UTC, datetime`, `from psalm_saga.batch_session import drafts_dir` (already imported names may be partial; keep existing ones), `from experiments.pipeline.models import GenerationJob, GenerationResult, JobAbandoned`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_full_pipeline.py -q`
Expected: PASS.

---

### Task 7: Runner: progress lines, abandoned path, item filter

**Files:**
- Modify: `experiments/pipeline/runner.py`
- Modify: `tests/experiments/test_runner.py`

**Interfaces:**
- Consumes: `ProgressSink`, `JobProgress` (Task 3); `JobAbandoned` (Task 1); `Registry.claim_next_pending(plan, item_ids)`, `Registry.count_pending`, `Registry.mark_abandoned` (Task 1); `BACKEND_REGISTRY` (unchanged).
- Produces:
  - `run_job(job, resolver, runs_dir, progress: ProgressSink | None = None) -> tuple[str, dict]`. It writes the artifacts, trace, metadata, and `progress.log`. `JobAbandoned` propagates to the caller after the same artifacts are written.
  - `run_pending(registry, plan_name, resolver, runs_dir, workers, item_ids: Collection[str] | None = None) -> None`. Prints `[i/N] <item> start` and `[i/N] <item> done|abandoned|failed (<mm:ss>)` lines.

- [ ] **Step 1: Update the fake backend and write the failing tests**

In `tests/experiments/test_runner.py`, `_FakeBackend.run` gains `progress` as a third parameter. Add:

```python
class _AbandoningBackend:
    def run(self, job, input_ref, progress):
        raise JobAbandoned(
            "fix-loop cap reached",
            artifacts={"attempts/1/drafts/story/ABANDONED.md": "cap"},
            trace=[{"type": "AIMessage", "content": "stuck"}],
            config={"attempts": 1},
        )


def test_run_pending_records_an_abandoned_job_and_keeps_its_evidence(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _AbandoningBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    resolver = _resolver(tmp_path, item_ids=["a"])
    runs_dir = tmp_path / "runs"

    runner.run_pending(registry, "pilot", resolver, runs_dir, workers=1)

    assert registry.status_counts("pilot") == {"abandoned": 1}
    job_dir = runs_dir / _job("a").job_id
    assert (job_dir / "attempts" / "1" / "drafts" / "story" / "ABANDONED.md").read_text() == "cap"
    assert (job_dir / "progress.log").exists()
    registry.close()


def test_run_pending_limits_work_to_the_requested_items(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b"), _job("c")])
    resolver = _resolver(tmp_path, item_ids=["a", "b", "c"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1, item_ids={"b"})

    assert registry.status_counts("pilot") == {"done": 1, "pending": 2}
    registry.close()


def test_run_pending_prints_start_and_finish_lines(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    resolver = _resolver(tmp_path, item_ids=["a"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1)

    out = capsys.readouterr().out
    assert "[1/1] a start" in out
    assert "[1/1] a done" in out
    registry.close()
```

Add `from experiments.pipeline.models import JobAbandoned` to the test imports. Confirm the existing `_FakeBackend` tests still pass with the new signature.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_runner.py -q`
Expected: FAIL (`run_pending` has no `item_ids`; no abandoned path; no printed lines).

- [ ] **Step 3: Implement**

Rewrite `experiments/pipeline/runner.py` around these pieces:

```python
def _persist(
    output_dir: Path,
    job: GenerationJob,
    artifacts: dict[str, str],
    trace: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    """Write artifacts, trace, and metadata for one job into its output folder."""
    for filename, content in artifacts.items():
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    trace_lines = "\n".join(json.dumps(entry) for entry in trace)
    (output_dir / "trace.jsonl").write_text(f"{trace_lines}\n" if trace else "", encoding="utf-8")
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
        "length_range": job.length_range,
        "config": config,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
```

`run_job` now:

```python
def run_job(
    job: GenerationJob,
    resolver: InputResolver,
    runs_dir: Path,
    progress: ProgressSink | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run one job through its backend and persist its output.

    Raises `JobAbandoned` (after persisting the attempts' evidence) if every story attempt was
    abandoned, and any other exception for real failures.
    """
    output_dir = runs_dir / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    sink = progress or NullProgress()
    backend = BACKEND_REGISTRY[job.condition]
    input_ref = resolver.resolve(job)
    try:
        result = backend.run(job, input_ref, sink)
    except JobAbandoned as exc:
        _persist(output_dir, job, exc.artifacts, exc.trace, exc.config)
        raise
    _persist(output_dir, job, result.artifacts, result.trace, result.config)
    return str(output_dir), result.config
```

Note: `output_dir` is created before the backend runs, so `progress.log` (written by `JobProgress`) has a place to go. `JobProgress` is constructed by the runner worker, not here.

`run_pending` gets `item_ids` and counting:

```python
def run_pending(
    registry: Registry,
    plan_name: str,
    resolver: InputResolver,
    runs_dir: Path,
    workers: int,
    item_ids: Collection[str] | None = None,
) -> None:
    total = registry.count_pending(plan_name, item_ids)
    counter = itertools.count(1)
    counter_lock = threading.Lock()

    def _worker_loop() -> None:
        while True:
            job = registry.claim_next_pending(plan_name, item_ids)
            if job is None:
                return
            with counter_lock:
                index = next(counter)
            label = f"[{index}/{total}] {job.item_id}"
            (runs_dir / job.job_id).mkdir(parents=True, exist_ok=True)
            progress = JobProgress(prefix=label, log_path=runs_dir / job.job_id / "progress.log")
            print(f"{label} start", flush=True)  # noqa: T201
            started = time.monotonic()
            try:
                output_dir, config = run_job(job, resolver, runs_dir, progress)
            except JobAbandoned as exc:
                registry.mark_abandoned(job.job_id, reason=exc.reason, config=exc.config)
                outcome = "abandoned"
            except Exception as exc:  # noqa: BLE001 — one bad job must never stop the pool
                registry.mark_failed(job.job_id, error=str(exc))
                outcome = "failed"
                logger.warning("Job %s failed: %s", job.job_id, exc)
            else:
                registry.mark_done(job.job_id, output_dir=output_dir, config=config)
                outcome = "done"
            elapsed = _format_elapsed(time.monotonic() - started)
            print(f"{label} {outcome} ({elapsed})", flush=True)  # noqa: T201
```

Also add the module helper `_format_elapsed(seconds: float) -> str` returning `f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"`. Keep the pool/executor block at the end unchanged.

Imports: `itertools`, `threading`, `time`, `from collections.abc import Collection`, `from experiments.pipeline.models import GenerationJob, JobAbandoned`, `from experiments.pipeline.progress import JobProgress, NullProgress, ProgressSink`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments -q`
Expected: PASS.

---

### Task 8: CLI: `run --item`

**Files:**
- Modify: `experiments/pipeline/cli.py`
- Modify: `tests/experiments/test_cli.py`

**Interfaces:**
- Consumes: `run_pending(..., item_ids=...)` (Task 7).
- Produces: `run --item <corpus_id>` (repeatable). Unknown ids exit with a message listing the valid ids. With no `--item`, behaviour is unchanged (`item_ids=None`).

- [ ] **Step 1: Write the failing tests**

Change the fake in `test_run_command_expands_then_delegates_to_run_pending` to accept the new argument:

```python
    def fake_run_pending(_registry, plan_name, _resolver, run_dir, workers, item_ids=None) -> None:
        captured["plan_name"] = plan_name
        captured["run_dir"] = run_dir
        captured["workers"] = workers
        captured["item_ids"] = item_ids
```

and assert `captured["item_ids"] is None`.

Add:

```python
def test_run_command_passes_repeated_items_through(monkeypatch, tmp_path) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cli, "run_pending",
        lambda _r, _p, _res, _d, _w, item_ids=None: captured.update(item_ids=item_ids),
    )

    cli.main([
        "run", "--plan", str(plan_path), "--corpus", str(corpus_path),
        "--runs-dir", str(tmp_path / "runs"), "--item", "satire_a", "--item", "gothic_a",
    ])

    assert captured["item_ids"] == {"satire_a", "gothic_a"}


def test_run_command_rejects_an_unknown_item_and_lists_valid_ids(tmp_path) -> None:
    corpus_path = _write_corpus(tmp_path)
    plan_path = _write_plan(tmp_path)

    with pytest.raises(SystemExit, match="satire_a"):
        cli.main([
            "run", "--plan", str(plan_path), "--corpus", str(corpus_path),
            "--runs-dir", str(tmp_path / "runs"), "--item", "not_a_real_id",
        ])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments/test_cli.py -q`
Expected: FAIL (`--item` is not a recognised argument).

- [ ] **Step 3: Implement**

In `_parse_args`, on the `run` subparser:

```python
    run_parser.add_argument(
        "--item",
        action="append",
        dest="items",
        default=None,
        metavar="CORPUS_ID",
        help="Run only this corpus item (repeatable). Done jobs are never repeated.",
    )
```

In `_cmd_run`:

```python
def _cmd_run(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    corpus = _load_corpus(args.corpus)
    item_ids = _validated_items(args.items, corpus)
    registry = Registry(args.runs_dir / "runs.db")
    try:
        registry.insert_jobs(expand_jobs(plan, corpus))
        resolver = InputResolver(args.data_dir)
        run_pending(registry, plan.name, resolver, args.runs_dir, workers=args.workers, item_ids=item_ids)
        print_status(registry, plan.name)
    finally:
        registry.close()


def _validated_items(items: list[str] | None, corpus: pd.DataFrame) -> set[str] | None:
    """Return the requested corpus ids, or None when no `--item` was given.

    Raises SystemExit listing the valid ids if any requested id is not in the corpus.
    """
    if not items:
        return None
    valid = set(corpus["id"])
    unknown = sorted(set(items) - valid)
    if unknown:
        raise SystemExit(
            f"Unknown corpus id(s): {', '.join(unknown)}. Valid ids: {', '.join(sorted(valid))}"
        )
    return set(items)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments -q`
Expected: PASS.

---

### Task 9: Verify the full suite and lint

**Files:** none changed.

- [ ] **Step 1: Run the whole experiments suite**

Run: `.venv/Scripts/python.exe -m pytest tests/experiments -q`
Expected: all tests pass (previously 41, now more).

- [ ] **Step 2: Run ruff on the touched modules**

Run: `.venv/Scripts/python.exe -m ruff check experiments/pipeline tests/experiments`
Expected: no new findings. Fix any that appear in the new code (for example the `# noqa` comments or long lines) without changing behaviour.

- [ ] **Step 3: Run a dry expansion to check the new fields**

Run: `.venv/Scripts/python.exe -m experiments.pipeline.cli expand --plan experiments/plans/pilot.yaml --corpus experiments/data/stories/pilot_corpus.parquet --runs-dir <scratchpad>/runs`
Expected: `Plan 'pilot': 2 jobs described, 2 newly inserted.` (or 0 newly inserted if a scratch registry already exists). The job ids are unchanged from before this plan.

---

### Task 10: Documentation

**Files:**
- Modify: `docs/EXPERIMENTS.md`

- [ ] **Step 1: Update the guide**

Make these changes in `docs/EXPERIMENTS.md`:
- §5.2 (Run): add the `--item` flag with an example (`--item adventure_two_years_before_the_mast_ch6`), and say that done jobs are never repeated.
- §5 (new subsection): describe the progress lines (`[i/N] <item> start`, stage lines such as `draft ch 2/5`, and `progress.log` in each job folder).
- §4 (Plans): document the optional `length:` key, which overrides the per-item ±10% band, and state that Task D needs it.
- §6.1 (Registry): add the `abandoned` status with its meaning, and say that `retry --failed` also requeues abandoned jobs.
- §6.2 (Job folder): add `attempts.jsonl`, `attempts/<n>/`, `progress.log`, and the `length_range` and `realised_words` fields in `metadata.json`.
- §8 (Troubleshooting): replace the `No story was completed` row with two rows: one for `abandoned` (read `error` and `attempts.jsonl`), and one for `failed` with that error text.

- [ ] **Step 2: Check the links**

Run: `grep -n "EXPERIMENTS.md\|§" docs/EXPERIMENTS.md | head -40` and confirm each `§` reference still points to the right heading.

---

### Task 11: Manual check (needs your approval first)

**Files:** none changed.

This task spends model budget. Do not run it until you approve.

- [ ] **Step 1: Ask for approval**

Ask: "OK to rerun `domestic_de_ooievaar_komt` with `--item` as the manual check? It is one live story attempt, up to three attempts, so cost is up to three full pipeline runs."

- [ ] **Step 2: Run it once approved**

Run: `.venv/Scripts/python.exe -m experiments.pipeline.cli run --plan experiments/plans/pilot.yaml --corpus experiments/data/stories/pilot_corpus.parquet --item domestic_de_ooievaar_komt`
Expected:
- Start and stage lines print as the job runs.
- The job ends `done` or `abandoned`. If `abandoned`, `error` in `runs.db` holds the real reason, and `runs/<job_id>/attempts.jsonl` lists each attempt.
- The other pilot job is still `done` and untouched.

---

## Self-Review

**1. Spec coverage**
- §1 length band: Task 2 (band, plan override, identity), Task 5 (directive, `realised_words`).
- §2 progress: Task 3 (stage mapping, `JobProgress`), Task 4 (streaming), Task 7 (start/finish lines and `progress.log`).
- §3 `--item`: Task 1 (`claim_next_pending` filter, `count_pending`), Task 7 (runner passes `item_ids`), Task 8 (CLI and validation). Done jobs are not repeated: covered by the pending-only claim and tested in Task 1.
- §4 abandonment: Task 6 (attempt loop, `attempts/<n>/`, `attempts.jsonl`, real failure reason), Task 1 (`abandoned` status and `mark_abandoned`), Task 7 (abandoned path persists evidence), Task 1 (`retry` covers abandoned).
- Testing list from the spec: band derivation (Task 2), `--item` filtering and done-not-reclaimed (Task 1, Task 7), attempt sequencing with a stub (Task 6), status transitions (Task 1), stage detection (Task 3). Manual check: Task 11.
- Gap: none against the spec, apart from the flagged `fix_loop_activated` deviation.

**2. Placeholder scan:** no TBD or TODO. Task 4 and Task 6 contain prose guidance around code blocks; the code that matters is written out. Task 6's `_run_attempt` is described step by step, not written in full. This is the one place an implementer has to write substantial code, so the next step should check it against the streaming code in Task 4.

**3. Type consistency**
- `GenerationBackend.run(job, input_ref, progress)` is used the same way in Tasks 4, 6, 7 and in the tests.
- `run_job(job, resolver, runs_dir, progress=None)` matches its callers in Task 7.
- `run_pending(..., item_ids=None)` matches the CLI call in Task 8 and the test fake.
- `JobAbandoned(reason, artifacts=, trace=, config=)` is constructed in Task 6 and read in Task 7 as `exc.reason`, `exc.config`, `exc.artifacts`, `exc.trace`.
- `Registry.claim_next_pending(plan_name, item_ids)` and `count_pending(plan_name, item_ids)` match Task 7.
- `_realised_words(artifacts, promoted)` is defined in Task 5 and reused in Task 6 with the `winning_docs` argument.
- `MAX_STORY_ATTEMPTS` is defined in Task 6; the prompt text in Task 4 does not depend on it.
