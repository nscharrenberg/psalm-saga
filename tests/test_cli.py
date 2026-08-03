from __future__ import annotations

import pytest
import typer
from rich.prompt import Prompt

import psalm_saga.cli as cli_module
from psalm_saga.cli import DISCUSS_FURTHER, WRITE_OWN_ANSWER, _prompt_for_interrupt
from psalm_saga.tools.ask_human import (  # type: ignore[import-untyped]
    STILL_EXPLORING_PREFIX,
    make_ask_human_tool,
)


class _FakeSelect:
    def __init__(self, result: str | None) -> None:
        self._result = result

    def ask(self) -> str | None:
        return self._result


class _FakePending:
    """Stands in for langgraph's real pending-interrupt object, which exposes `.value`."""

    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


def test_prompt_for_interrupt_without_options_falls_back_to_free_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Prompt, "ask", lambda *a, **k: "The lighthouse keeper's daughter")

    reply = _prompt_for_interrupt({"question": "Who is the rival?"})

    assert reply == "The lighthouse keeper's daughter"


def test_prompt_for_interrupt_with_options_selecting_an_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_choices: list[str] = []

    def fake_select(_message: str, choices: list[str]) -> _FakeSelect:
        captured_choices.extend(choices)
        return _FakeSelect("His own daughter")

    monkeypatch.setattr(cli_module.questionary, "select", fake_select)

    reply = _prompt_for_interrupt(
        {"question": "Who is the rival?", "options": ["A harbor official", "His own daughter"]}
    )

    assert reply == "His own daughter"
    assert captured_choices == [
        "A harbor official",
        "His own daughter",
        WRITE_OWN_ANSWER,
        DISCUSS_FURTHER,
    ]


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


def test_prompt_for_interrupt_consumes_real_ask_human_payload_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crosses the ask_human -> CLI boundary: builds the payload via the real tool (not a hand-
    written dict), wraps it the way langgraph's real pending interrupt does (a `.value` attribute,
    not a bare dict), and feeds that into `_prompt_for_interrupt` -- catching a future key-name
    drift between the two sides, and exercising the `pending.value` unwrap no other test reaches.
    """
    captured_payload: dict[str, object] = {}

    def fake_interrupt(payload: dict[str, object]) -> str:
        captured_payload.update(payload)
        return "unused"

    monkeypatch.setattr("psalm_saga.tools.ask_human.interrupt", fake_interrupt)

    tool = make_ask_human_tool(non_interactive=False)  # type: ignore[no-untyped-call]
    tool.invoke(
        {
            "question": "Who is the rival?",
            "options": ["A harbor official", "His own daughter"],
            "why": "shapes the antagonist",
        }
    )

    captured_choices: list[str] = []

    def fake_select(_message: str, choices: list[str]) -> _FakeSelect:
        captured_choices.extend(choices)
        return _FakeSelect("His own daughter")

    monkeypatch.setattr(cli_module.questionary, "select", fake_select)

    reply = _prompt_for_interrupt(_FakePending(captured_payload))

    assert reply == "His own daughter"
    assert captured_choices == [
        "A harbor official",
        "His own daughter",
        WRITE_OWN_ANSWER,
        DISCUSS_FURTHER,
    ]
