"""Tests for `experiments.pipeline.backends.full_pipeline` (C1).

Mirrors the mocking pattern `tests/unit/test_batch_cli.py` uses for
`psalm_saga.batch_cli`: `build_agent`/`open_sqlite_checkpointer` are
monkeypatched so no live model call happens, and the fake agent writes
files into the session's real `docs/` directory to simulate what the
skills would have produced.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from experiments.pipeline.backends import full_pipeline
from experiments.pipeline.generators import _DEFAULT_MODELS
from experiments.pipeline.length import directive_for
from experiments.pipeline.models import GenerationJob, JobAbandoned
from experiments.pipeline.progress import NullProgress
from experiments.pipeline.resolver import ResolvedInput
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


class _FakeAI:
    def __init__(self, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeAgent:
    """Writes each doc and yields LangGraph `subgraphs=True` stream items.

    `docs_to_write` is a dict or a list of `(path, content)` pairs (a list allows
    the same path to be written twice, as a fix pass does). `namespaces` maps a
    path to the subgraph namespace its write is reported from; unmapped paths
    are reported from the top-level graph (`()`).
    """

    def __init__(
        self,
        docs_dir: Path,
        docs_to_write: dict[str, str] | list[tuple[str, str]],
        namespaces: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._docs_dir = docs_dir
        self._docs_to_write = (
            list(docs_to_write.items()) if isinstance(docs_to_write, dict) else list(docs_to_write)
        )
        self._namespaces = namespaces or {}

    def stream(
        self, _payload: dict[str, Any], **_kwargs: Any
    ) -> Iterator[tuple[tuple[str, ...], str, Any]]:
        for rel_path, content in self._docs_to_write:
            target = self._docs_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            yield (self._namespaces.get(rel_path, ()), "updates", {"model": {"messages": [_FakeAI(tool_calls=[
                {"name": "write_file", "args": {"file_path": rel_path}}
            ])]}})
        yield ((), "updates", {"model": {"messages": [_FakeAI(content="done")]}})


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


_FINISHED_DRAFT = {
    "drafts/story/story-plan.md": "# The Statue — Story Plan\n",
    "drafts/story/chapter-1-only.md": "# Chapter 1: Only\n\nOnce upon a time.",
    "drafts/story/DONE.md": "Whole-story review passed clean.",
}


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
        full_pipeline, "build_agent", lambda *_a, **_kw: _FakeAgent(docs_dir, dict(_FINISHED_DRAFT))
    )

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="A statue learns to give.", source_path=tmp_path)

    result = backend.run(_job(), input_ref, NullProgress())

    assert result.artifacts["drafts/story/DONE.md"] == "Whole-story review passed clean."
    assert "stories/story.md" in result.artifacts
    assert "Once upon a time." in result.artifacts["stories/story.md"]
    assert len(result.trace) >= 2
    assert result.trace[0]["type"] == "HumanMessage"
    assert "A statue learns to give." in result.trace[0]["content"]
    assert result.trace[-1]["content"] == "done"
    assert result.config["promoted_stories"] == ["story"]


def test_run_reports_stage_changes_from_the_stream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_run_raises_when_no_draft_carries_a_done_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline,
        "build_agent",
        lambda *_a, **_kw: _FakeAgent(docs_dir, {"drafts/story/story-plan.md": "# Story — Story Plan\n"}),
    )

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)

    with pytest.raises(RuntimeError, match="No story was completed"):
        backend.run(_job(), input_ref, NullProgress())


def test_run_resolves_generator_family_and_records_the_model_id_in_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _FakeAgent(docs_dir, dict(_FINISHED_DRAFT))
    )

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)

    result = backend.run(_job(), input_ref, NullProgress())

    assert result.config["orchestration_model_name"] == _DEFAULT_MODELS["frontier"]
    assert result.config["subagent_model_name"] == _DEFAULT_MODELS["frontier"]
    assert result.config["task"] == "A"
    assert result.config["condition"] == "C1"
    assert "prompt_template_sha256" in result.config


def test_run_uses_the_batch_bootstrap_skill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_args: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent(docs_dir, dict(_FINISHED_DRAFT))

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(full_pipeline, "build_agent", fake_build_agent)

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)

    backend.run(_job(), input_ref, NullProgress())

    assert captured_kwargs["bootstrap_skill"] == full_pipeline.BATCH_BOOTSTRAP_SKILL


def test_run_handles_task_d_without_a_missing_instruction_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _FakeAgent(docs_dir, dict(_FINISHED_DRAFT))
    )

    backend = full_pipeline.FullPipelineBackend()
    input_ref = ResolvedInput(kind="scratch_spec", content="# Scratch spec content", source_path=tmp_path)

    result = backend.run(_job(task="D"), input_ref, NullProgress())

    assert "# Scratch spec content" in result.trace[0]["content"]
    assert result.config["task"] == "D"


def test_run_prepends_the_length_directive_when_a_range_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    captured: dict[str, Any] = {}

    class _Capture(_FakeAgent):
        def stream(self, payload: dict[str, Any], **kwargs: Any) -> Iterator[tuple[str, Any]]:
            captured["instruction"] = payload["messages"][0]["content"]
            return super().stream(payload, **kwargs)

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _Capture(docs_dir, dict(_FINISHED_DRAFT))
    )

    job = GenerationJob(
        plan_name="pilot",
        task="A",
        condition="C1",
        item_id="satire_the_happy_prince",
        generator_family="frontier",
        language="english",
        length_range="270-330",
    )
    result = full_pipeline.FullPipelineBackend().run(
        job,
        ResolvedInput(kind="premise", content="premise text", source_path=tmp_path),
        NullProgress(),
    )

    assert captured["instruction"].startswith(directive_for("270-330") + "\n\n")
    assert "270" in captured["instruction"]
    assert "330" in captured["instruction"]
    assert result.config["length_range"] == "270-330"
    assert result.config["realised_words"] == len(result.artifacts["stories/story.md"].split())


def test_run_leaves_the_instruction_unchanged_without_a_length_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    docs_dir = session_directory(settings, "session-fixed") / "docs"
    captured: dict[str, Any] = {}

    class _Capture(_FakeAgent):
        def stream(self, payload: dict[str, Any], **kwargs: Any) -> Iterator[tuple[str, Any]]:
            captured["instruction"] = payload["messages"][0]["content"]
            return super().stream(payload, **kwargs)

    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: "session-fixed")
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(
        full_pipeline, "build_agent", lambda *_a, **_kw: _Capture(docs_dir, dict(_FINISHED_DRAFT))
    )

    result = full_pipeline.FullPipelineBackend().run(
        _job(), ResolvedInput(kind="premise", content="premise text", source_path=tmp_path), NullProgress()
    )

    assert captured["instruction"].startswith("Generate a complete story from this premise")
    assert captured["instruction"].endswith("premise text")
    assert result.config["length_range"] is None
    assert result.config["realised_words"] == len(result.artifacts["stories/story.md"].split())


def _abandoned_draft(reason: str) -> dict[str, str]:
    return {
        "drafts/story/story-plan.md": "# Story — Story Plan\n",
        "drafts/story/story-review.md": "Partial",
        "drafts/story/ABANDONED.md": reason,
    }


def _run_with_attempt_sequence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drafts_per_attempt: list[Any],
    progress: Any = None,
    namespaces: dict[str, tuple[str, ...]] | None = None,
) -> Any:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    sessions = iter(f"session-{i}" for i in range(1, 10))
    monkeypatch.setattr(full_pipeline, "Settings", lambda: settings)
    monkeypatch.setattr(full_pipeline, "generate_session_id", lambda: next(sessions))
    monkeypatch.setattr(full_pipeline, "open_sqlite_checkpointer", _fake_checkpointer)

    attempts = iter(drafts_per_attempt)

    def fake_build_agent(_settings: Settings, *, session_id: str, **_kw: Any) -> _FakeAgent:
        docs_dir = session_directory(settings, session_id) / "docs"
        return _FakeAgent(docs_dir, next(attempts), namespaces)

    monkeypatch.setattr(full_pipeline, "build_agent", fake_build_agent)
    input_ref = ResolvedInput(kind="premise", content="premise text", source_path=tmp_path)
    return full_pipeline.FullPipelineBackend().run(_job(), input_ref, progress or NullProgress())


class _RecordingSink:
    def __init__(self) -> None:
        self.stages: list[str] = []

    def stage(self, label: str) -> None:
        self.stages.append(label)


def test_an_abandoned_attempt_is_retried_from_scratch_and_can_succeed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sink = _RecordingSink()
    result = _run_with_attempt_sequence(
        monkeypatch, tmp_path,
        [_abandoned_draft("cap reached once"), dict(_FINISHED_DRAFT)],
        progress=sink,
    )
    assert result.config["promoted_stories"] == ["story"]
    assert result.config["winning_attempt"] == 2
    assert result.config["psalm_saga_session_id"] == "session-2"
    assert result.config["attempts"] == 2
    timeline = [json.loads(line) for line in result.artifacts["attempts.jsonl"].splitlines()]
    events = [entry["event"] for entry in timeline]
    assert events == ["attempt_started", "attempt_abandoned", "attempt_started", "attempt_done"]
    assert timeline[1]["reason"] == "cap reached once"
    assert all("at" in entry for entry in timeline)
    assert "attempts/1/drafts/story/ABANDONED.md" in result.artifacts
    assert "attempts/2/drafts/story/DONE.md" in result.artifacts
    # Top-level artifacts are the winning attempt's docs.
    assert result.artifacts["drafts/story/DONE.md"] == "Whole-story review passed clean."
    assert "drafts/story/ABANDONED.md" not in result.artifacts
    assert {entry["attempt"] for entry in result.trace} == {1, 2}
    assert sink.stages.count("attempt 1/3") == 1
    assert sink.stages.count("attempt 2/3") == 1
    assert "attempt 3/3" not in sink.stages


def test_three_abandoned_attempts_raise_job_abandoned_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reason = "Abandoned after three chapter review attempts: Character still Partial."
    with pytest.raises(JobAbandoned) as info:
        _run_with_attempt_sequence(monkeypatch, tmp_path, [_abandoned_draft(reason)] * 3)
    assert info.value.reason == reason
    assert "attempts/3/drafts/story/ABANDONED.md" in info.value.artifacts
    assert info.value.config["attempts"] == 3
    timeline = [json.loads(line)["event"] for line in info.value.artifacts["attempts.jsonl"].splitlines()]
    assert timeline.count("attempt_abandoned") == 3
    assert {entry["attempt"] for entry in info.value.trace} == {1, 2, 3}


def test_no_done_and_no_abandoned_marker_is_a_failure_not_an_abandonment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="none was abandoned"):
        _run_with_attempt_sequence(
            monkeypatch, tmp_path, [{"drafts/story/story-plan.md": "# plan\n"}]
        )


def test_a_write_from_a_subgraph_namespace_is_reported_and_traced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sink = _RecordingSink()
    namespace = ("tools:abc123", "model:def456")
    result = _run_with_attempt_sequence(
        monkeypatch, tmp_path, [dict(_FINISHED_DRAFT)],
        progress=sink,
        namespaces={"drafts/story/chapter-1-only.md": namespace},
    )
    assert "chapter 1" in sink.stages
    namespaced = [entry for entry in result.trace if entry.get("namespace") == "tools:abc123/model:def456"]
    assert len(namespaced) == 1
    top_level = [entry for entry in result.trace if entry.get("namespace") == ""]
    assert top_level  # the top-level writes carry an empty namespace


def test_a_rewritten_chapter_before_a_review_is_a_fix_loop_but_new_chapters_are_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sink = _RecordingSink()
    writes = [
        ("drafts/story/story-plan.md", "# Story — Story Plan\n"),
        ("drafts/story/chapter-1-a.md", "# Chapter 1\n\nOne."),
        ("drafts/story/story-review.md", "Covered"),
        ("drafts/story/chapter-2-b.md", "# Chapter 2\n\nTwo."),
        ("drafts/story/story-review.md", "Partial"),
        ("drafts/story/chapter-2-b.md", "# Chapter 2\n\nTwo, fixed."),
        ("drafts/story/story-review.md", "Covered"),
        ("drafts/story/story-review.md", "Whole story covered"),
        ("drafts/story/DONE.md", "Whole-story review passed clean."),
    ]
    result = _run_with_attempt_sequence(monkeypatch, tmp_path, [writes], progress=sink)
    timeline = [json.loads(line) for line in result.artifacts["attempts.jsonl"].splitlines()]
    fixes = [entry for entry in timeline if entry["event"] == "fix_loop_activated"]
    assert len(fixes) == 1
    assert fixes[0]["cycle"] == 1
    assert fixes[0]["review_file"] == "drafts/story/story-review.md"
    assert fixes[0]["attempt"] == 1
    assert sink.stages.count("fix attempt 1") == 1
    assert "fix attempt 2" not in sink.stages
