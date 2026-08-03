from __future__ import annotations

import pytest
import typer
from rich.prompt import Prompt

import psalm_saga.cli as cli_module
from psalm_saga.cli import DISCUSS_FURTHER, WRITE_OWN_ANSWER, _prompt_for_interrupt
from psalm_saga.tools.ask_human import STILL_EXPLORING_PREFIX  # type: ignore[import-untyped]


class _FakeSelect:
    def __init__(self, result: str | None) -> None:
        self._result = result

    def ask(self) -> str | None:
        return self._result


def test_prompt_for_interrupt_without_options_falls_back_to_free_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Prompt, "ask", lambda *a, **k: "The lighthouse keeper's daughter")

    reply = _prompt_for_interrupt({"question": "Who is the rival?"})

    assert reply == "The lighthouse keeper's daughter"


def test_prompt_for_interrupt_with_options_selecting_an_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module.questionary, "select", lambda *a, **k: _FakeSelect("His own daughter")
    )

    reply = _prompt_for_interrupt(
        {"question": "Who is the rival?", "options": ["A harbor official", "His own daughter"]}
    )

    assert reply == "His own daughter"


def test_prompt_for_interrupt_write_own_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module.questionary, "select", lambda *a, **k: _FakeSelect(WRITE_OWN_ANSWER)
    )
    monkeypatch.setattr(Prompt, "ask", lambda *a, **k: "A ghost who used to run the lighthouse")

    reply = _prompt_for_interrupt(
        {"question": "Who is the rival?", "options": ["A harbor official", "His own daughter"]}
    )

    assert reply == "A ghost who used to run the lighthouse"


def test_prompt_for_interrupt_discuss_further_wraps_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module.questionary, "select", lambda *a, **k: _FakeSelect(DISCUSS_FURTHER)
    )
    monkeypatch.setattr(Prompt, "ask", lambda *a, **k: "not sure, tell me more about option 2")

    reply = _prompt_for_interrupt(
        {"question": "Who is the rival?", "options": ["A harbor official", "His own daughter"]}
    )

    assert reply.startswith(STILL_EXPLORING_PREFIX)
    assert "not sure, tell me more about option 2" in reply


def test_prompt_for_interrupt_cancelled_menu_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module.questionary, "select", lambda *a, **k: _FakeSelect(None))

    with pytest.raises(typer.Exit):
        _prompt_for_interrupt(
            {"question": "Who is the rival?", "options": ["A harbor official", "His own daughter"]}
        )
