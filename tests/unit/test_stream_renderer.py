"""Tests for `psalm_saga.stream_renderer.extract_tool_call_lines`.

Moved here (from a private helper in `cli.py`) so both `psalm-saga` and
`psalm-saga-batch` can render tool-dispatch status lines from the same
best-effort LangGraph `updates`-mode payload shape.
"""

from __future__ import annotations

from typing import Any

from psalm_saga.stream_renderer import extract_tool_call_lines


class _FakeToolCallMessage:
    def __init__(self, tool_calls: list[dict[str, Any]]) -> None:
        self.tool_calls = tool_calls


def test_extract_tool_call_lines_names_a_plain_tool_call() -> None:
    update = {"model": {"messages": [_FakeToolCallMessage([{"name": "write_file"}])]}}

    assert extract_tool_call_lines(update) == ["write_file"]


def test_extract_tool_call_lines_names_the_dispatched_subagent() -> None:
    update = {
        "model": {
            "messages": [
                _FakeToolCallMessage(
                    [{"name": "task", "args": {"subagent_type": "chapter-writer"}}]
                )
            ]
        }
    }

    assert extract_tool_call_lines(update) == ["dispatching chapter-writer"]


def test_extract_tool_call_lines_returns_empty_for_no_model_key() -> None:
    assert extract_tool_call_lines({}) == []


def test_extract_tool_call_lines_returns_empty_on_malformed_payload() -> None:
    assert extract_tool_call_lines({"model": "not-a-dict-with-messages"}) == []
