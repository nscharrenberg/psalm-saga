from __future__ import annotations

import pytest

from psalm_saga.tools.ask_human import (  # type: ignore[import-untyped]
    NON_INTERACTIVE_REPLY,
    STILL_EXPLORING_PREFIX,
    format_discussion_reply,
    make_ask_human_tool,
)


def test_non_interactive_short_circuits_without_calling_interrupt() -> None:
    tool = make_ask_human_tool(non_interactive=True)  # type: ignore[no-untyped-call]
    result = tool.invoke({"question": "Sibling or mentor?"})
    assert result == NON_INTERACTIVE_REPLY


def test_interactive_payload_includes_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_interrupt(payload: dict[str, object]) -> str:
        captured.update(payload)
        return "A harbor official who wants the letters stopped"

    monkeypatch.setattr("psalm_saga.tools.ask_human.interrupt", fake_interrupt)

    tool = make_ask_human_tool(non_interactive=False)  # type: ignore[no-untyped-call]
    result = tool.invoke(
        {
            "question": "Who is the rival?",
            "options": ["A harbor official who wants the letters stopped", "His own daughter"],
            "why": "shapes the antagonist",
        }
    )

    assert captured["question"] == "Who is the rival?"
    assert captured["why"] == "shapes the antagonist"
    assert captured["options"] == [
        "A harbor official who wants the letters stopped",
        "His own daughter",
    ]
    assert result == "A harbor official who wants the letters stopped"


def test_interactive_payload_omits_options_when_not_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_interrupt(payload: dict[str, object]) -> str:
        captured.update(payload)
        return "some answer"

    monkeypatch.setattr("psalm_saga.tools.ask_human.interrupt", fake_interrupt)

    tool = make_ask_human_tool(non_interactive=False)  # type: ignore[no-untyped-call]
    tool.invoke({"question": "What's the setting?"})

    assert "options" not in captured


def test_format_discussion_reply_wraps_with_prefix() -> None:
    wrapped = format_discussion_reply("I'm not sure yet, tell me more about option 2")
    assert wrapped == f"{STILL_EXPLORING_PREFIX}I'm not sure yet, tell me more about option 2"
