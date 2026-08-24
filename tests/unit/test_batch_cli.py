"""Tests for `psalm_saga.batch_cli`'s argument parsing/validation and
per-story instruction building — the pieces that don't need a running
agent. See the main-loop tests further down this file for `run_batch`.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from psalm_saga import batch_cli
from psalm_saga.batch_cli import _build_story_instruction, _parse_args
from psalm_saga.batch_session import promoted_story_count, stories_dir
from psalm_saga.settings import Settings


def test_parse_args_defaults_combine_to_mixed_for_context() -> None:
    args = _parse_args(["--count", "3", "--mode", "context", "--context", "a spooky forest"])

    assert args.combine == "mixed"


def test_parse_args_forces_combine_separate_for_variant() -> None:
    args = _parse_args(
        ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "separate"]
    )

    assert args.combine == "separate"


def test_parse_args_rejects_combine_mixed_for_variant() -> None:
    with pytest.raises(SystemExit):
        _parse_args(
            ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "mixed"]
        )


def test_parse_args_rejects_count_below_one() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--count", "0", "--mode", "scratch"])


def test_parse_args_collects_repeated_context_paths() -> None:
    args = _parse_args(
        [
            "--count",
            "1",
            "--mode",
            "context",
            "--context-path",
            "a.txt",
            "--context-path",
            "b.txt",
        ]
    )

    assert args.context_paths == [Path("a.txt"), Path("b.txt")]


def test_build_story_instruction_for_scratch_mode() -> None:
    message = _build_story_instruction(1, 5, "scratch", "mixed", None, set())

    assert "story 1 of 5" in message
    assert "Mode: scratch" in message


def test_build_story_instruction_includes_existing_names() -> None:
    message = _build_story_instruction(2, 5, "context", "mixed", ["a spooky forest"], {"story-a"})

    assert "story-a" in message


class _FakeAgent:
    def __init__(self, on_stream: Any) -> None:
        self._on_stream = on_stream

    def stream(self, *_args: Any, **_kwargs: Any) -> Iterator[Any]:
        self._on_stream()
        return iter(())


@contextmanager
def _fake_checkpointer(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    yield None


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def _quiet_console() -> Console:
    return Console(file=io.StringIO())


def test_run_batch_stops_once_count_is_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    calls: list[int] = []

    def on_stream() -> None:
        n = len(calls) + 1
        calls.append(n)
        (stories_dir(settings, session_id) / f"story-{n}").mkdir(parents=True)

    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_a: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent(on_stream)

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", fake_build_agent)

    args = _parse_args(["--count", "3", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 3
    assert promoted_story_count(settings, session_id) == 3
    assert captured_kwargs["bootstrap_skill"] == batch_cli.BATCH_BOOTSTRAP_SKILL


def test_run_batch_gives_up_after_the_attempt_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    calls: list[int] = []

    def on_stream() -> None:
        calls.append(len(calls) + 1)
        # never promotes anything — simulates a systemically broken run

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _FakeAgent(on_stream))

    args = _parse_args(["--count", "2", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 2 * batch_cli.MAX_ATTEMPT_MULTIPLIER
    assert promoted_story_count(settings, session_id) == 0


def test_run_batch_resumes_and_only_tops_up_the_remainder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    (stories_dir(settings, session_id) / "already-done").mkdir(parents=True)
    calls: list[int] = []

    def on_stream() -> None:
        n = len(calls) + 1
        calls.append(n)
        (stories_dir(settings, session_id) / f"story-{n}").mkdir(parents=True)

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _FakeAgent(on_stream))

    args = _parse_args(["--count", "3", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 2  # only the missing 2, not 3
    assert promoted_story_count(settings, session_id) == 3
