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
