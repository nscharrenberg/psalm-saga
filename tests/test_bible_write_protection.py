from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime

from psalm_saga.agents.subagents import build_subagents
from psalm_saga.config import Settings
from psalm_saga.tools import BIBLE_WRITE_PROTECTION


def _settings() -> Settings:
    return Settings(model="anthropic:claude-haiku-4-5")


def _tool(tools, name: str):  # type: ignore[no-untyped-def]
    return next(t for t in tools if t.name == name)


def _call(tool, **kwargs):  # type: ignore[no-untyped-def]
    runtime = ToolRuntime(
        state={}, context=None, config={}, stream_writer=lambda _: None,
        tool_call_id="t1", store=None,
    )
    return tool.func(runtime=runtime, **kwargs).content


def test_bible_write_protection_blocks_write_and_edit_on_story_bible(tmp_path: Path) -> None:
    """The permission rule itself must actually block write_file/edit_file on the bible.

    This is the mechanism that has to hold for the corruption bug to be fixed: models
    were able to hand-author story_bible.json's raw JSON text via write_file/edit_file,
    producing malformed JSON that update_story_bible's validate-before-write would have
    rejected. If this rule doesn't block those tools, nothing downstream matters.
    """
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    middleware = FilesystemMiddleware(backend=backend, _permissions=BIBLE_WRITE_PROTECTION)
    write_file = _tool(middleware.tools, "write_file")
    edit_file = _tool(middleware.tools, "edit_file")

    write_result = _call(write_file, file_path="/story_bible.json", content="{}")
    assert "permission denied" in write_result.lower()
    assert not (tmp_path / "story_bible.json").exists()

    # Also blocks the exact "spiral" side-files seen in the real corruption incident
    # (story_bible_cleaned.json, story_bible_v2.json, etc).
    decoy_result = _call(write_file, file_path="/story_bible_cleaned.json", content="{}")
    assert "permission denied" in decoy_result.lower()

    # edit_file is blocked too, not just write_file.
    (tmp_path / "story_bible.json").write_text('{"mode": "from_scratch"}')
    edit_result = _call(
        edit_file,
        file_path="/story_bible.json",
        old_string='{"mode": "from_scratch"}',
        new_string='{"mode": "from_source"}',
    )
    assert "permission denied" in edit_result.lower()
    assert (tmp_path / "story_bible.json").read_text() == '{"mode": "from_scratch"}'

    # Unrelated files are unaffected.
    other_result = _call(write_file, file_path="/draft.md", content="hello")
    assert "permission denied" not in other_result.lower()
    assert (tmp_path / "draft.md").exists()


def test_subagents_that_can_see_the_bible_deny_direct_writes_to_it(tmp_path: Path) -> None:
    """Every subagent gets write_file/edit_file for free from FilesystemMiddleware,
    regardless of its own declared ``tools`` list, so each one must carry the bible
    write-protection permission explicitly rather than relying on tool omission."""
    subagents = build_subagents(_settings(), tmp_path)
    assert subagents, "expected at least one subagent"

    for agent in subagents:
        assert agent.get("permissions") == BIBLE_WRITE_PROTECTION, (
            f"{agent['name']} is missing BIBLE_WRITE_PROTECTION -- its inherited "
            "write_file/edit_file tools could still hand-corrupt story_bible.json"
        )
