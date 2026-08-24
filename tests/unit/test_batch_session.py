"""Tests for `psalm_saga.batch_session` — directory layout, name
bookkeeping, and promotion for `psalm-saga-batch` sessions.
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
    story_final_dir,
)
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def test_drafts_and_stories_dir_paths(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert drafts_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "drafts"
    assert stories_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "stories"


def test_existing_story_names_empty_when_nothing_exists(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert existing_story_names(settings, "session-1") == set()


def test_existing_story_names_combines_drafts_and_stories(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    story_draft_dir(settings, "session-1", "draft-only").mkdir(parents=True)
    story_final_dir(settings, "session-1", "finished-one").mkdir(parents=True)

    assert existing_story_names(settings, "session-1") == {"draft-only", "finished-one"}


def test_promoted_story_count(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    story_final_dir(settings, "session-1", "story-a").mkdir(parents=True)
    story_final_dir(settings, "session-1", "story-b").mkdir(parents=True)

    assert promoted_story_count(settings, "session-1") == 2


def test_promote_story_copies_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    draft.mkdir(parents=True)
    (draft / "story-a-spec.md").write_text("spec content")

    final = promote_story(settings, "session-1", "story-a")

    assert final == story_final_dir(settings, "session-1", "story-a")
    assert (final / "story-a-spec.md").read_text() == "spec content"


def test_promote_story_missing_draft_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with pytest.raises(FileNotFoundError):
        promote_story(settings, "session-1", "missing")


def test_promote_story_already_promoted_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    draft.mkdir(parents=True)
    story_final_dir(settings, "session-1", "story-a").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        promote_story(settings, "session-1", "story-a")
