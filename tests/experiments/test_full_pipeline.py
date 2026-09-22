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
    # The backend wraps the raw premise in a task-specific instruction template
    # (see `_TASK_INSTRUCTIONS`) before sending it as the message content, so
    # this checks the premise made it through rather than exact equality.
    assert "A statue learns to give." in result.trace[0]["content"]
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
