"""Tests for `psalm_saga.story_assembly` — turning a batch story's draft
directory (plan + numbered chapter files) into the single reader-facing
document `promote_story` writes to `docs/stories/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.story_assembly import assemble_story, extract_title, find_chapter_files


def test_extract_title_from_story_plan_heading() -> None:
    plan_text = "# The House After Storm — Story Plan\n\n## Title and Logline\n"

    assert extract_title(plan_text, fallback="fallback-name") == "The House After Storm"


def test_extract_title_falls_back_when_heading_not_found() -> None:
    plan_text = "Some plan text with no matching heading.\n"

    assert extract_title(plan_text, fallback="the-quiet-archive") == "The Quiet Archive"


def test_find_chapter_files_sorts_numerically_not_lexically(tmp_path: Path) -> None:
    (tmp_path / "chapter-10-the-end.md").write_text("ten")
    (tmp_path / "chapter-2-the-middle.md").write_text("two")
    (tmp_path / "chapter-1-the-start.md").write_text("one")
    (tmp_path / "the-story-plan.md").write_text("not a chapter")

    result = find_chapter_files(tmp_path)

    assert [p.name for p in result] == [
        "chapter-1-the-start.md",
        "chapter-2-the-middle.md",
        "chapter-10-the-end.md",
    ]


def test_find_chapter_files_ignores_non_chapter_files(tmp_path: Path) -> None:
    (tmp_path / "chapter-1-only.md").write_text("chapter text")
    (tmp_path / "my-story-spec.md").write_text("spec")
    (tmp_path / "my-story-plan.md").write_text("plan")
    (tmp_path / "my-story-review.md").write_text("review")
    (tmp_path / "DONE.md").write_text("done")

    result = find_chapter_files(tmp_path)

    assert [p.name for p in result] == ["chapter-1-only.md"]


def test_assemble_story_combines_title_and_chapters_in_order(tmp_path: Path) -> None:
    (tmp_path / "my-story-plan.md").write_text(
        "# My Story — Story Plan\n\nDetails.\n", encoding="utf-8"
    )
    (tmp_path / "chapter-1-beginning.md").write_text(
        "# Chapter 1: Beginning\n\nOnce upon a time.", encoding="utf-8"
    )
    (tmp_path / "chapter-2-end.md").write_text("# Chapter 2: End\n\nThe end.", encoding="utf-8")

    result = assemble_story(tmp_path, "my-story")

    assert result.startswith("# My Story\n\n")
    assert result.index("## Chapter 1: Beginning") < result.index("## Chapter 2: End")
    assert "Once upon a time." in result
    assert "The end." in result


def test_assemble_story_demotes_chapter_headings_below_the_book_title(
    tmp_path: Path,
) -> None:
    """The book title is the only `#` (H1) in the assembled document —
    each chapter's own `# Chapter N: ...` heading is demoted to `##` so it
    reads as a section of the book, not a second book title."""
    (tmp_path / "my-story-plan.md").write_text(
        "# My Story — Story Plan\n", encoding="utf-8"
    )
    (tmp_path / "chapter-1-only.md").write_text(
        "# Chapter 1: Only\n\nText.", encoding="utf-8"
    )

    result = assemble_story(tmp_path, "my-story")

    h1_lines = [line for line in result.splitlines() if line.startswith("# ") and not line.startswith("## ")]
    assert h1_lines == ["# My Story"]
    assert "## Chapter 1: Only" in result


def test_assemble_story_leaves_a_chapter_with_no_leading_heading_unchanged(
    tmp_path: Path,
) -> None:
    (tmp_path / "my-story-plan.md").write_text(
        "# My Story — Story Plan\n", encoding="utf-8"
    )
    (tmp_path / "chapter-1-only.md").write_text(
        "Once upon a time, with no heading at all.", encoding="utf-8"
    )

    result = assemble_story(tmp_path, "my-story")

    assert "Once upon a time, with no heading at all." in result
    assert "## " not in result


def test_assemble_story_falls_back_to_story_name_when_plan_missing(tmp_path: Path) -> None:
    (tmp_path / "chapter-1-only.md").write_text("# Chapter 1: Only\n\nText.")

    result = assemble_story(tmp_path, "no-plan-here")

    assert result.startswith("# No Plan Here\n\n")


def test_assemble_story_raises_when_no_chapters_found(tmp_path: Path) -> None:
    (tmp_path / "empty-story-plan.md").write_text(
        "# Empty Story — Story Plan\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="No chapter files"):
        assemble_story(tmp_path, "empty-story")
