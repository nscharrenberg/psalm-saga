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


def test_refuses_when_chapter_indices_are_duplicated(tmp_path: Path) -> None:
    """Defense-in-depth regression test: a duplicate `index` value (the exact corruption that
    caused draft.md to silently repeat one chapter's content for two different chapter slots)
    must be refused loudly, not read from the same file twice."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Broken Book",
        chapters=[
            Chapter(index=1, title="First", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="Second", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="Also Second", status=ChapterStatus.APPROVED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "First chapter text.")
    _write_chapter(tmp_path, 2, "Second chapter text.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "duplicate" in result.lower()
    assert "2" in result
    assert not (tmp_path / "draft.md").exists()


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


def test_strips_redundant_leading_heading_matching_chapter_title(tmp_path: Path) -> None:
    """Regression test: writer.md tells writer-agent not to include a heading line (assemble_draft
    adds one), but in practice it's not reliably followed -- observed in production as three
    different self-titling formats across chapters in the same book (a bare title line, a markdown
    "## Title" line, and a "Chapter N: Title" line), each producing a visibly duplicated heading
    in draft.md. assemble_draft must strip a redundant leading title line in any of these forms
    before prepending its own canonical heading, regardless of what writer-agent did."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="A Festive Beginning", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="Signs of Trouble", status=ChapterStatus.APPROVED),
            Chapter(index=3, title="Overcoming the Crisis", status=ChapterStatus.APPROVED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "A Festive Beginning\n\nThe festival began at dawn.")
    _write_chapter(tmp_path, 2, "## Signs of Trouble\n\nSomething felt off.")
    _write_chapter(tmp_path, 3, "Chapter 3: Overcoming the Crisis\n\nThey faced it together.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    # Each title appears exactly once (assemble_draft's own canonical heading) -- not duplicated.
    assert draft.count("A Festive Beginning") == 1
    assert draft.count("Signs of Trouble") == 1
    assert draft.count("Overcoming the Crisis") == 1
    assert "The festival began at dawn." in draft
    assert "Something felt off." in draft
    assert "They faced it together." in draft


def test_does_not_strip_a_first_line_that_is_not_the_chapter_title(tmp_path: Path) -> None:
    """Guard against false positives: a chapter that genuinely opens with prose (not a redundant
    heading) must be left untouched, even if that prose happens to start with a capitalized
    phrase."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[Chapter(index=1, title="A Festive Beginning", status=ChapterStatus.APPROVED)],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "The Merchant arrived before anyone else, as always.")

    tool = make_assemble_draft_tool(tmp_path)
    _invoke(tool)  # type: ignore[no-untyped-call]

    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    assert "The Merchant arrived before anyone else, as always." in draft


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
