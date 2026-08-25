"""Tests for `psalm_saga.batch_session` — directory layout, name
bookkeeping, and promotion for `psalm-saga-batch` sessions.

A promoted story is a single `docs/stories/<story_name>.md` file (the
title and chapters, assembled from the draft — see
`psalm_saga.story_assembly`), not a copy of the draft directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.batch_session import (
    drafts_dir,
    existing_story_names,
    promote_story,
    promoted_story_count,
    stories_dir,
    story_draft_dir,
    story_final_path,
)
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def _write_minimal_draft(draft: Path, story_name: str) -> None:
    draft.mkdir(parents=True)
    (draft / f"{story_name}-plan.md").write_text(
        "# A Story — Story Plan\n", encoding="utf-8"
    )
    (draft / "chapter-1-only.md").write_text(
        "# Chapter 1: Only\n\nOnce upon a time.", encoding="utf-8"
    )


def test_drafts_and_stories_dir_paths(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert drafts_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "drafts"
    assert stories_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "stories"


def test_story_final_path_is_a_single_markdown_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert story_final_path(settings, "session-1", "story-a") == stories_dir(
        settings, "session-1"
    ) / "story-a.md"


def test_existing_story_names_empty_when_nothing_exists(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert existing_story_names(settings, "session-1") == set()


def test_existing_story_names_combines_drafts_and_stories(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    story_draft_dir(settings, "session-1", "draft-only").mkdir(parents=True)
    final = story_final_path(settings, "session-1", "finished-one")
    final.parent.mkdir(parents=True)
    final.write_text("# Finished One\n", encoding="utf-8")

    assert existing_story_names(settings, "session-1") == {"draft-only", "finished-one"}


def test_promoted_story_count(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    for name in ("story-a", "story-b"):
        final = story_final_path(settings, "session-1", name)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text(f"# {name}\n", encoding="utf-8")

    assert promoted_story_count(settings, "session-1") == 2


def test_promote_story_assembles_title_and_chapters_into_one_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    _write_minimal_draft(draft, "story-a")

    final = promote_story(settings, "session-1", "story-a")

    assert final == story_final_path(settings, "session-1", "story-a")
    assert final.is_file()
    content = final.read_text(encoding="utf-8")
    assert content.startswith("# A Story\n\n")
    assert "Once upon a time." in content


def test_promote_story_does_not_copy_working_documents(tmp_path: Path) -> None:
    """Only the assembled prose is promoted — spec/plan/review/DONE.md stay
    in the draft directory as the audit trail, never in `docs/stories/`."""
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    _write_minimal_draft(draft, "story-a")
    (draft / "story-a-spec.md").write_text("spec content", encoding="utf-8")
    (draft / "story-a-review.md").write_text("review content", encoding="utf-8")
    (draft / "DONE.md").write_text("done", encoding="utf-8")

    promote_story(settings, "session-1", "story-a")

    promoted_names = {p.name for p in stories_dir(settings, "session-1").iterdir()}
    assert promoted_names == {"story-a.md"}


def test_promote_story_missing_draft_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with pytest.raises(FileNotFoundError):
        promote_story(settings, "session-1", "missing")


def test_promote_story_already_promoted_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    draft.mkdir(parents=True)
    final = story_final_path(settings, "session-1", "story-a")
    final.parent.mkdir(parents=True)
    final.write_text("already here", encoding="utf-8")

    with pytest.raises(FileExistsError):
        promote_story(settings, "session-1", "story-a")
