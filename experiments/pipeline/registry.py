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
from collections.abc import Collection
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
    config_json TEXT,
    length_range TEXT
);
"""

_SELECT_COLUMNS = (
    "job_id, plan_name, task, condition, item_id, generator_family, "
    "language, replicate, is_pilot, status, output_dir, error, "
    "started_at, finished_at, config_json, length_range"
)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    """Add `column` to `table` if an older database predates it."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


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
        _started_at, _finished_at, config_json, length_range,
    ) = row
    job = GenerationJob(
        plan_name=plan_name, task=task, condition=condition, item_id=item_id,
        generator_family=generator_family, language=language,
        replicate=replicate, is_pilot=bool(is_pilot), length_range=length_range,
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
            _ensure_column(self._conn, "jobs", "length_range", "TEXT")
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
                         language, replicate, is_pilot, status, length_range)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        job.job_id, job.plan_name, job.task, job.condition, job.item_id,
                        job.generator_family, job.language, job.replicate, int(job.is_pilot),
                        job.length_range,
                    ),
                )
                inserted += cursor.rowcount
            self._conn.commit()
            return inserted

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
                # Claimed by another connection between the SELECT and this
                # UPDATE (or the row no longer matches) — never return a job
                # this call didn't actually claim.
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

    def mark_abandoned(self, job_id: str, *, reason: str, config: dict[str, Any]) -> None:
        """Record that every story attempt for a job was abandoned, with the reason."""
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'abandoned', error = ?, config_json = ?, "
                "finished_at = ? WHERE job_id = ?",
                (reason, json.dumps(config), datetime.now(UTC).isoformat(), job_id),
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
        """Reset every `failed` or `abandoned` job for `plan_name` back to `pending`.

        Returns the count changed.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE jobs SET status = 'pending', error = NULL "
                "WHERE plan_name = ? AND status IN ('failed', 'abandoned')",
                (plan_name,),
            )
            self._conn.commit()
            return cursor.rowcount
