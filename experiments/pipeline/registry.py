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
                f"SELECT {_SELECT_COLUMNS} FROM jobs WHERE plan_name = ? AND status = 'pending' LIMIT 1",  # noqa: S608 (_SELECT_COLUMNS is a constant, plan_name is parameterized)
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
