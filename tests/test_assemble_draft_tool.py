from pathlib import Path

from psalm_saga.dimensions import Chapter, ChapterStatus, GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.assemble import make_assemble_draft_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def _write_bible(session_dir: Path, bible: StoryBible) -> None:
    (session_dir / "story_bible.json").write_text(bible.model_dump_json())


def _write_chapter(session_dir: Path, index: int, text: str) -> None:
    chapters_dir = session_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    (chapters_dir / f"chapter_{index:02d}.md").write_text(text, encoding="utf-8")


def test_refuses_when_bible_missing(tmp_path: Path) -> None:
    tool = make_assemble_draft_tool(tmp_path)
    assert "Cannot assemble" in _invoke(tool)  # type: ignore[no-untyped-call]


def test_refuses_when_no_chapters_planned(tmp_path: Path) -> None:
    _write_bible(tmp_path, StoryBible(mode=GenerationMode.FROM_SCRATCH, title="Untitled Draft"))
    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "no chapters yet" in result


def test_refuses_when_a_chapter_is_not_approved(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.DRAFTED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    _write_chapter(tmp_path, 2, "She wrote back before she could stop herself.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "chapter 2 (drafted)" in result
    assert not (tmp_path / "draft.md").exists()


def test_refuses_when_an_approved_chapter_file_is_missing(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED)],
    )
    _write_bible(tmp_path, bible)
    # deliberately don't write chapters/chapter_01.md

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "missing from chapters/" in result
    assert "chapter_01.md" in result


def test_assembles_approved_chapters_in_order_with_title_prefixes(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.APPROVED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    _write_chapter(tmp_path, 2, "She wrote back before she could stop herself.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    assert draft.startswith("# Return to Sender")
    assert draft.index("The First Letter") < draft.index("Mara found the letter")
    assert draft.index("Mara found the letter") < draft.index("The Reply")
    assert draft.index("The Reply") < draft.index("She wrote back")


def test_include_unapproved_assembles_a_chapter_that_exhausted_its_revision_budget(
    tmp_path: Path,
) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.DRAFTED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    _write_chapter(tmp_path, 2, "She wrote back before she could stop herself.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool, include_unapproved=True)  # type: ignore[no-untyped-call]

    assert result.startswith("OK")
    assert "chapter 2" in result
    assert "drafted" in result

    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    assert "Mara found the letter" in draft
    assert "She wrote back" in draft


def test_include_unapproved_still_refuses_if_a_required_chapter_file_is_missing(
    tmp_path: Path,
) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.DRAFTED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    # deliberately don't write chapters/chapter_02.md

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool, include_unapproved=True)  # type: ignore[no-untyped-call]

    assert "Cannot assemble" in result
    assert "missing from chapters/" in result
    assert "chapter_02.md" in result
    assert not (tmp_path / "draft.md").exists()
