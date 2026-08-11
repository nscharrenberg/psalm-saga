from pathlib import Path

from psalm_saga.agents.subagents import build_subagents  # type: ignore[import-untyped]
from psalm_saga.config import Settings  # type: ignore[import-untyped]


def _agent(settings: Settings, tmp_path: Path, name: str):  # type: ignore[no-untyped-def]
    agents = build_subagents(settings, tmp_path)
    return next(a for a in agents if a["name"] == name)


def _tool_names(agent) -> set[str]:  # type: ignore[no-untyped-def]
    return {getattr(t, "name", "") for t in agent["tools"]}


def test_chapter_planner_agent_is_registered_without_ask_human(
    settings: Settings, tmp_path: Path
) -> None:
    agent = _agent(settings, tmp_path, "chapter-planner-agent")
    assert "update_story_bible" in _tool_names(agent)
    assert "ask_human" not in _tool_names(agent)


def test_chapter_reviewer_agent_is_registered_without_ask_human(
    settings: Settings, tmp_path: Path
) -> None:
    agent = _agent(settings, tmp_path, "chapter-reviewer-agent")
    assert "ask_human" not in _tool_names(agent)


def test_chapter_reviewer_agent_uses_update_chapter_not_update_story_bible(
    settings: Settings, tmp_path: Path
) -> None:
    """Regression test: chapter-reviewer-agent previously had generic `update_story_bible` and
    had to hand-compute `array_position = chapter.index - 1` for every RFC 6902 patch -- which,
    in production, it got wrong repeatedly for one chapter and, when its own `test`-op guard
    caught the mismatch, "fixed" the failure by overwriting the guarded `index` field instead of
    its own math, corrupting the chapter list (two chapters sharing one index, another index
    missing entirely). `update_chapter` removes that computation from the agent-facing surface
    entirely, so `update_story_bible` must no longer be available to this subagent at all."""
    agent = _agent(settings, tmp_path, "chapter-reviewer-agent")
    assert "update_chapter" in _tool_names(agent)
    assert "update_story_bible" not in _tool_names(agent)


def test_chapter_reviewer_agent_reads_chapters_via_read_chapter_file(
    settings: Settings, tmp_path: Path
) -> None:
    agent = _agent(settings, tmp_path, "chapter-reviewer-agent")
    assert "read_chapter_file" in _tool_names(agent)


def test_writer_agent_uses_index_addressed_chapter_file_tools(
    settings: Settings, tmp_path: Path
) -> None:
    """Regression test for the root cause of the two-different-drafts-per-chapter bug: the
    orchestrator's own delegation text named `chapters/chapter_1.md` (unpadded) for chapter 1,
    writer-agent wrote there literally via the generic write_file tool, and a later retry (after
    assemble_draft correctly reported it missing under the padded name) produced a second,
    different draft at the correctly-padded `chapters/chapter_01.md`. write_chapter_file/
    read_chapter_file take the chapter's own `index` integer and compute the canonical filename
    internally, so no agent ever constructs or transcribes a chapter path again."""
    agent = _agent(settings, tmp_path, "writer-agent")
    assert "write_chapter_file" in _tool_names(agent)
    assert "read_chapter_file" in _tool_names(agent)
