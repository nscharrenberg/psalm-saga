"""Tests for `psalm_saga.cli`'s argument parsing and the length-directive
injection into `build_agent`'s `system_prompt` for a fresh vs. resumed
session — the pieces that don't need a real model or terminal.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from psalm_saga import cli
from psalm_saga.cli import _parse_args, _run_one_session
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


def test_parse_args_defaults_length_and_chapters() -> None:
    args = _parse_args([])

    assert args.length_spec.category == "short-story"
    assert args.chapter_spec.mode == "auto"


def test_parse_args_resolves_explicit_length_and_chapters() -> None:
    args = _parse_args(["--length", "novella", "--chapters", "5"])

    assert args.length_spec.category == "novella"
    assert args.chapter_spec.count == 5


def test_parse_args_rejects_invalid_length() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--length", "not-a-category"])


class _ImmediatelyDoneSession:
    """Fakes `prompt_toolkit.PromptSession`: the first `.prompt()` call
    raises `EOFError`, so `run_session` exits right after `_run_one_session`
    starts it — enough to exercise `_run_one_session` without a real
    terminal.
    """

    def prompt(self, *_args: Any, **_kwargs: Any) -> str:
        raise EOFError


class _FakeState:
    values: dict[str, Any] = {}


class _FakeAgent:
    def get_state(self, _config: Any) -> _FakeState:
        return _FakeState()


@contextmanager
def _fake_checkpointer(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    yield None


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def test_run_one_session_injects_length_directive_for_a_fresh_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_a: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent()

    monkeypatch.setattr(cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(cli, "build_agent", fake_build_agent)

    directive = "Story length directive: novella, target 17,500-39,999 words. Chapter count: auto."
    _run_one_session(settings, "session-1", Console(), _ImmediatelyDoneSession(), directive)

    assert captured_kwargs["system_prompt"] == directive


def test_run_one_session_omits_length_directive_for_a_resumed_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    session_directory(settings, session_id).mkdir(parents=True)
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_a: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent()

    monkeypatch.setattr(cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(cli, "build_agent", fake_build_agent)

    directive = "Story length directive: novella, target 17,500-39,999 words. Chapter count: auto."
    _run_one_session(settings, session_id, Console(), _ImmediatelyDoneSession(), directive)

    assert captured_kwargs["system_prompt"] == ""
