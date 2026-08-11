from pathlib import Path

from psalm_saga.tools.chapter_files import (  # type: ignore[import-untyped]
    make_read_chapter_file_tool,
    make_write_chapter_file_tool,
)


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def test_write_chapter_file_uses_zero_padded_canonical_name(tmp_path: Path) -> None:
    """Regression test for the root cause: the orchestrator's own delegation text named
    `chapters/chapter_1.md` (unpadded) for chapter 1, writer-agent wrote there literally, and a
    later retry (after assemble_draft correctly reported it missing under the padded name)
    produced a *second*, different draft at the correctly-padded `chapters/chapter_01.md` --
    leaving two different stories on disk for the same chapter. Callers must never construct the
    filename themselves; passing the bare `index` must always land on the one canonical path."""
    tool = make_write_chapter_file_tool(tmp_path)
    result = _invoke(tool, index=1, content="Chapter one prose.")  # type: ignore[no-untyped-call]
    assert result.startswith("OK")
    assert (tmp_path / "chapters" / "chapter_01.md").exists()
    assert not (tmp_path / "chapters" / "chapter_1.md").exists()
    content = (tmp_path / "chapters" / "chapter_01.md").read_text(encoding="utf-8")
    assert content == "Chapter one prose."


def test_write_chapter_file_creates_chapters_dir_if_missing(tmp_path: Path) -> None:
    tool = make_write_chapter_file_tool(tmp_path)
    assert not (tmp_path / "chapters").exists()
    _invoke(tool, index=3, content="Chapter three.")  # type: ignore[no-untyped-call]
    assert (tmp_path / "chapters" / "chapter_03.md").exists()


def test_write_chapter_file_overwrites_unconditionally(tmp_path: Path) -> None:
    """A revision pass must always land in the same place the first draft did -- no
    write_file-style "already exists, write to a new file" refusal, and no need for the caller to
    choose between a write tool and an edit tool."""
    tool = make_write_chapter_file_tool(tmp_path)
    _invoke(tool, index=2, content="First draft.")  # type: ignore[no-untyped-call]
    result = _invoke(tool, index=2, content="Revised draft.")  # type: ignore[no-untyped-call]
    assert result.startswith("OK")
    assert (tmp_path / "chapters" / "chapter_02.md").read_text(encoding="utf-8") == "Revised draft."
    # Only one file for this chapter -- no orphaned alternate-named file.
    assert list((tmp_path / "chapters").iterdir()) == [tmp_path / "chapters" / "chapter_02.md"]


def test_read_chapter_file_returns_content(tmp_path: Path) -> None:
    write_tool = make_write_chapter_file_tool(tmp_path)
    read_tool = make_read_chapter_file_tool(tmp_path)
    _invoke(write_tool, index=5, content="Chapter five prose.")  # type: ignore[no-untyped-call]

    result = _invoke(read_tool, index=5)  # type: ignore[no-untyped-call]
    assert result == "Chapter five prose."


def test_read_chapter_file_reports_not_yet_written_instead_of_raw_not_found(tmp_path: Path) -> None:
    """Regression test: agents were seen searching for the wrong filename variant and getting
    raw file-not-found errors. A clear, unambiguous "not written yet" message (naming the exact
    canonical path that was checked) is easier for a model to act on correctly than a generic
    not-found error that invites guessing at alternate filenames."""
    tool = make_read_chapter_file_tool(tmp_path)
    result = _invoke(tool, index=7)  # type: ignore[no-untyped-call]
    assert "not been written yet" in result.lower() or "not yet" in result.lower()
    assert "chapter_07.md" in result
