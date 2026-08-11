from pathlib import Path

from psalm_saga.tools.finalize import make_finalize_story_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def test_refuses_when_draft_missing(tmp_path: Path) -> None:
    tool = make_finalize_story_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "draft.md does not exist" in result
    assert not (tmp_path / "final_story.md").exists()


def test_copies_draft_to_final_story_verbatim(tmp_path: Path) -> None:
    """Regression test for editor-agent silently truncating a 6-chapter, ~25k-character
    draft.md to ~10k characters (3 chapters) when asked to regenerate the whole book in a
    single write_file call. finalize_story() must guarantee final_story.md is a complete,
    correct copy of every chapter *before* editor-agent ever runs, so nothing depends on one
    large generation reproducing the entire book correctly."""
    draft_content = "# My Book\n\n## Chapter One\n\nSome prose.\n\n## Chapter Two\n\nMore prose.\n"
    (tmp_path / "draft.md").write_text(draft_content, encoding="utf-8")
    tool = make_finalize_story_tool(tmp_path)

    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    final_content = (tmp_path / "final_story.md").read_text(encoding="utf-8")
    assert final_content == draft_content


def test_overwrites_an_existing_final_story_with_a_fresh_copy(tmp_path: Path) -> None:
    """Re-running finalize_story (e.g. a redo/resume) must reset final_story.md to match the
    current draft.md, not leave stale content from a previous attempt."""
    (tmp_path / "draft.md").write_text("Current draft content.", encoding="utf-8")
    (tmp_path / "final_story.md").write_text("Stale content from a previous run.", encoding="utf-8")
    tool = make_finalize_story_tool(tmp_path)

    _invoke(tool)  # type: ignore[no-untyped-call]

    assert (tmp_path / "final_story.md").read_text(encoding="utf-8") == "Current draft content."
