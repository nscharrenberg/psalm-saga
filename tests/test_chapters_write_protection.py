from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime

from psalm_saga.agents.subagents import build_subagents
from psalm_saga.config import Settings
from psalm_saga.tools.chapter_files import CHAPTERS_WRITE_PROTECTION


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


def test_chapters_write_protection_blocks_write_and_edit_on_chapter_files(tmp_path: Path) -> None:
    """The permission rule itself must actually block write_file/edit_file on chapters/*.md.

    This is the mechanism that has to hold for the two-different-drafts-per-chapter bug to stay
    fixed: writer-agent was able to write chapter prose via the generic write_file tool using
    whatever filename it (or the orchestrator's delegation text) happened to construct, rather
    than being forced through write_chapter_file's single canonical, index-derived path. If this
    rule doesn't block those tools, nothing downstream matters.
    """
    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    middleware = FilesystemMiddleware(backend=backend, _permissions=CHAPTERS_WRITE_PROTECTION)
    write_file = _tool(middleware.tools, "write_file")
    edit_file = _tool(middleware.tools, "edit_file")

    write_result = _call(write_file, file_path="/chapters/chapter_01.md", content="prose")
    assert "permission denied" in write_result.lower()
    assert not (tmp_path / "chapters" / "chapter_01.md").exists()

    # The exact wrong-filename variant seen in the real incident is blocked too, not just the
    # canonical name -- the point is no chapter file can be hand-written at all.
    decoy_result = _call(write_file, file_path="/chapters/chapter_1.md", content="prose")
    assert "permission denied" in decoy_result.lower()

    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "chapter_01.md").write_text("original")
    edit_result = _call(
        edit_file,
        file_path="/chapters/chapter_01.md",
        old_string="original",
        new_string="tampered",
    )
    assert "permission denied" in edit_result.lower()
    assert (tmp_path / "chapters" / "chapter_01.md").read_text() == "original"

    # Unrelated files are unaffected.
    other_result = _call(write_file, file_path="/draft.md", content="hello")
    assert "permission denied" not in other_result.lower()
    assert (tmp_path / "draft.md").exists()


def test_subagents_that_touch_chapters_deny_direct_writes_to_them(tmp_path: Path) -> None:
    """Every subagent gets write_file/edit_file for free from FilesystemMiddleware regardless of
    its own declared ``tools`` list, so each one must carry the chapters write-protection
    permission explicitly rather than relying on tool omission."""
    subagents = build_subagents(_settings(), tmp_path)
    assert subagents, "expected at least one subagent"

    for agent in subagents:
        permissions = agent.get("permissions") or []
        assert any(
            rule.paths == CHAPTERS_WRITE_PROTECTION[0].paths
            and rule.operations == CHAPTERS_WRITE_PROTECTION[0].operations
            and rule.mode == CHAPTERS_WRITE_PROTECTION[0].mode
            for rule in permissions
        ), (
            f"{agent['name']} is missing CHAPTERS_WRITE_PROTECTION -- its inherited "
            "write_file/edit_file tools could still hand-write a chapter under the wrong name"
        )
