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
