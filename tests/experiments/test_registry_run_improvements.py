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
    assert first is not None
    assert first.item_id == "b"
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


def test_insert_jobs_backfills_length_range_on_existing_rows(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    job = _job("a", "270-330")
    old = sqlite3.connect(db)
    old.execute(
        "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, plan_name TEXT NOT NULL, task TEXT NOT NULL, "
        "condition TEXT NOT NULL, item_id TEXT NOT NULL, generator_family TEXT NOT NULL, "
        "language TEXT NOT NULL, replicate INTEGER NOT NULL, is_pilot INTEGER NOT NULL, "
        "status TEXT NOT NULL, output_dir TEXT, error TEXT, started_at TEXT, finished_at TEXT, "
        "config_json TEXT)"
    )
    old.execute(
        "INSERT INTO jobs (job_id, plan_name, task, condition, item_id, generator_family, "
        "language, replicate, is_pilot, status) "
        "VALUES (?, 'pilot', 'A', 'C1', 'a', 'frontier', 'english', 0, 0, 'pending')",
        (job.job_id,),
    )
    old.commit()
    old.close()

    registry = Registry(db)
    assert registry.insert_jobs([job]) == 0
    registry.close()
    row = sqlite3.connect(db).execute(
        "SELECT length_range FROM jobs WHERE job_id = ?", (job.job_id,)
    ).fetchone()
    assert row[0] == "270-330"
