from pathlib import Path

from psalm_saga.dimensions import Chapter, ChapterStatus, GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.chapter import make_update_chapter_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def _write_bible(session_dir: Path, bible: StoryBible) -> None:
    (session_dir / "story_bible.json").write_text(bible.model_dump_json())


def test_refuses_when_bible_missing(tmp_path: Path) -> None:
    tool = make_update_chapter_tool(tmp_path)
    result = _invoke(tool, index=1, status="approved")  # type: ignore[no-untyped-call]
    assert "does not exist" in result


def test_updates_chapter_found_by_index_value_not_array_position(tmp_path: Path) -> None:
    """Regression test for the root cause of the chapter-2/chapter-3 corruption: two different
    agents independently miscomputed `array_position = index - 1` when hand-writing RFC 6902
    patches, and one of them, after its own guard op failed, force-overwrote the guarded field
    instead of fixing its math -- turning chapter 3 into a second chapter 2. This tool must never
    require the caller to know or compute an array position at all: it finds the chapter by its
    `index` field regardless of where that entry actually sits in the list.
    """
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Test",
        chapters=[
            Chapter(index=3, title="Third"),
            Chapter(index=1, title="First"),
            Chapter(index=2, title="Second"),
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_update_chapter_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool, index=2, status="approved", actual_summary="Second chapter happened."
    )
    assert result.startswith("OK")

    updated = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    by_index = {c.index: c for c in updated.chapters}
    assert by_index[2].status is ChapterStatus.APPROVED
    assert by_index[2].actual_summary == "Second chapter happened."
    # Untouched chapters must remain exactly as they were.
    assert by_index[1].status is ChapterStatus.PLANNED
    assert by_index[3].status is ChapterStatus.PLANNED


def test_refuses_when_index_not_found(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        chapters=[Chapter(index=1, title="Only"), Chapter(index=2, title="Second")],
    )
    _write_bible(tmp_path, bible)
    tool = make_update_chapter_tool(tmp_path)

    result = _invoke(tool, index=99, status="approved")  # type: ignore[no-untyped-call]
    assert "No chapter with index=99" in result
    assert "1" in result and "2" in result

    on_disk = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert on_disk.chapters[0].status is ChapterStatus.PLANNED


def test_refuses_ambiguously_when_index_is_duplicated(tmp_path: Path) -> None:
    """Defense-in-depth: even if some other bug reintroduces a duplicate index (exactly the
    corruption this tool exists to prevent), update_chapter must refuse rather than silently
    guessing which of the two entries the caller meant."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        chapters=[
            Chapter(index=1, title="First"),
            Chapter(index=2, title="Second"),
            Chapter(index=2, title="Also Second"),
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_update_chapter_tool(tmp_path)

    result = _invoke(tool, index=2, status="approved")  # type: ignore[no-untyped-call]
    assert "Multiple chapters" in result or "ambiguous" in result.lower()

    on_disk = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert all(c.status is ChapterStatus.PLANNED for c in on_disk.chapters)


def test_increment_revision_count_bumps_by_one_from_current_value(tmp_path: Path) -> None:
    """The orchestrator previously had to pass an absolute revision_count value it computed
    itself (1, then 2, then 3, ...) across separate calls -- another arithmetic mistake waiting
    to happen. This tool increments the stored value instead, so the caller never needs to know
    or track the current count."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH, chapters=[Chapter(index=1, title="A", revision_count=2)]
    )
    _write_bible(tmp_path, bible)
    tool = make_update_chapter_tool(tmp_path)

    result = _invoke(tool, index=1, increment_revision_count=True)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    on_disk = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert on_disk.chapters[0].revision_count == 3


def test_only_provided_fields_change(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        chapters=[
            Chapter(
                index=1,
                title="Keep Me",
                planned_summary="Keep this too.",
                actual_summary="Original summary.",
                status=ChapterStatus.DRAFTED,
                revision_count=1,
            )
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_update_chapter_tool(tmp_path)

    result = _invoke(tool, index=1, status="approved")  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    on_disk = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    chapter = on_disk.chapters[0]
    assert chapter.status is ChapterStatus.APPROVED
    assert chapter.title == "Keep Me"
    assert chapter.planned_summary == "Keep this too."
    assert chapter.actual_summary == "Original summary."
    assert chapter.revision_count == 1
