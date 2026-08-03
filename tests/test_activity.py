from __future__ import annotations

from psalm_saga.activity import (
    describe_tool_call,
    describe_tool_result,
    format_todos,
    namespace_label,
    shorten,
)


def test_shorten_collapses_whitespace_and_truncates() -> None:
    assert shorten("a\n\nb   c") == "a b c"
    long = "x" * 200
    result = shorten(long, limit=10)
    assert len(result) == 10
    assert result.endswith("…")


def test_format_todos_renders_all_three_statuses() -> None:
    todos = [
        {"content": "Extract dimensions", "status": "completed", "active_form": "Extracting dimensions"},
        {"content": "Write the draft", "status": "in_progress", "active_form": "Writing the draft"},
        {"content": "Edit the draft", "status": "pending", "active_form": "Editing the draft"},
    ]
    rendered = format_todos(todos)
    assert "☒" in rendered and "strike" in rendered and "Extract dimensions" in rendered
    assert "◐" in rendered and "Writing the draft" in rendered
    assert "☐" in rendered and "Edit the draft" in rendered


def test_format_todos_empty_list() -> None:
    assert format_todos([]) == ""


def test_describe_tool_call_task_delegation() -> None:
    desc = describe_tool_call("task", {"subagent_type": "writer-agent", "description": "Draft the story"})
    assert "delegating to" in desc
    assert "writer-agent" in desc
    assert "Draft the story" in desc


def test_describe_tool_call_task_without_recognized_subagent_key() -> None:
    # Should degrade gracefully rather than raise if the arg key doesn't match any candidate.
    desc = describe_tool_call("task", {"weird_key": "writer-agent"})
    assert "task(" in desc


def test_describe_tool_call_think() -> None:
    desc = describe_tool_call("think", {"thought": "The premise needs a stronger hook."})
    assert desc.startswith("🤔")
    assert "premise needs a stronger hook" in desc


def test_describe_tool_call_ask_human() -> None:
    desc = describe_tool_call("ask_human", {"question": "Sibling or mentor?", "why": "shapes the rival"})
    assert desc.startswith("❓")
    assert "Sibling or mentor?" in desc


def test_describe_tool_call_ask_human_with_options() -> None:
    desc = describe_tool_call(
        "ask_human",
        {
            "question": "Who is the rival?",
            "options": ["A harbor official", "His own daughter", "Someone else"],
        },
    )
    assert desc.startswith("❓")
    assert "Who is the rival?" in desc
    assert "(3 options)" in desc


def test_describe_tool_call_ask_human_without_options_unchanged() -> None:
    desc = describe_tool_call("ask_human", {"question": "Sibling or mentor?"})
    assert "options" not in desc


def test_describe_tool_call_known_tool_with_icon() -> None:
    desc = describe_tool_call("write_file", {"path": "story_bible.json"})
    assert desc.startswith("📝")


def test_describe_tool_call_unknown_tool_falls_back_to_arrow() -> None:
    desc = describe_tool_call("some_future_tool", {"x": 1})
    assert desc.startswith("→")


def test_describe_tool_call_no_args() -> None:
    assert describe_tool_call("validate_story_bible", {}) == "✅ validate_story_bible()"


def test_describe_tool_result_truncates_and_uses_icon() -> None:
    result = describe_tool_result("validate_story_bible", "OK: story_bible.json is schema-valid.")
    assert result.startswith("✅")


def test_describe_tool_result_flattens_content_blocks() -> None:
    content = [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]
    result = describe_tool_result("think", content)
    assert "part one" in result and "part two" in result


def test_namespace_label_empty() -> None:
    assert namespace_label(()) == ""


def test_namespace_label_formats_segments() -> None:
    label = namespace_label(("tools:abc123", "agent:writer-agent"))
    assert "tools" in label
    assert "agent" in label
