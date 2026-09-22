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
