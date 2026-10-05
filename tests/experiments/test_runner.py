"""Tests for `experiments.pipeline.runner`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.pipeline import runner
from experiments.pipeline.models import GenerationJob, GenerationResult, JobAbandoned, JobFailed
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

    def run(self, job: GenerationJob, input_ref, progress) -> GenerationResult:
        if self._fail:
            message = "simulated backend failure"
            raise RuntimeError(message)
        return GenerationResult(
            artifacts={"story.md": f"# Story for {job.item_id}\n\nfrom: {input_ref.content}"},
            trace=[{"type": "AIMessage", "content": "ok"}],
            config={"model": "fake-model"},
        )


class _AbandoningBackend:
    def run(self, job, input_ref, progress):
        progress.stage("abandoned")
        raise JobAbandoned(
            "fix-loop cap reached",
            artifacts={"attempts/1/drafts/story/ABANDONED.md": "cap"},
            trace=[{"type": "AIMessage", "content": "stuck"}],
            config={"attempts": 1},
        )


class _JobFailingBackend:
    def run(self, job, input_ref, progress):
        raise JobFailed(
            "story attempt errored",
            artifacts={"attempts/1/drafts/story/partial.md": "partial"},
            trace=[{"type": "AIMessage", "content": "boom"}],
            config={"attempts": 1},
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


def test_run_pending_records_an_abandoned_job_and_keeps_its_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_run_pending_records_a_job_failure_and_keeps_its_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _JobFailingBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    resolver = _resolver(tmp_path, item_ids=["a"])
    runs_dir = tmp_path / "runs"

    runner.run_pending(registry, "pilot", resolver, runs_dir, workers=1)

    assert registry.status_counts("pilot") == {"failed": 1}
    job_dir = runs_dir / _job("a").job_id
    assert (job_dir / "attempts" / "1" / "drafts" / "story" / "partial.md").read_text() == "partial"
    trace = (job_dir / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(trace[0]) == {"type": "AIMessage", "content": "boom"}
    registry.close()


def test_run_pending_limits_work_to_the_requested_items(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a"), _job("b"), _job("c")])
    resolver = _resolver(tmp_path, item_ids=["a", "b", "c"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1, item_ids={"b"})

    assert registry.status_counts("pilot") == {"done": 1, "pending": 2}
    registry.close()


def test_run_pending_with_an_empty_item_filter_does_nothing_and_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    resolver = _resolver(tmp_path, item_ids=["a"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1, item_ids=set())

    assert registry.status_counts("pilot") == {"pending": 1}
    assert capsys.readouterr().out == ""
    registry.close()


def test_run_pending_prints_start_and_finish_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(runner.BACKEND_REGISTRY, "C1", _FakeBackend())
    registry = Registry(tmp_path / "runs.db")
    registry.insert_jobs([_job("a")])
    resolver = _resolver(tmp_path, item_ids=["a"])

    runner.run_pending(registry, "pilot", resolver, tmp_path / "runs", workers=1)

    out = capsys.readouterr().out
    assert "[1/1] a start" in out
    assert "[1/1] a done" in out
    registry.close()
