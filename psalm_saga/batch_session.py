"""Directory layout, name bookkeeping, and promotion logic for
`psalm-saga-batch` sessions.

Batch sessions use `docs/drafts/<story_name>/` for work in progress and
`docs/stories/<story_name>/` for finished stories, instead of interactive
sessions' `docs/psalm-saga/<slug>-*.md` convention — see the design doc's
"Directory layout & session semantics" section. Every function here takes
the same `(settings, session_id)` pair `psalm_saga.session` uses, so a
batch session is just a normal session with a different `docs/` shape.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from psalm_saga.session import session_directory
from psalm_saga.settings import Settings

DRAFTS_DIRNAME = "drafts"
STORIES_DIRNAME = "stories"
DOCS_DIRNAME = "docs"


def drafts_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/drafts/` — every story's working directory."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / DRAFTS_DIRNAME


def stories_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/stories/` — every finished story."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / STORIES_DIRNAME


def story_draft_dir(settings: Settings, session_id: str, story_name: str) -> Path:
    """The story's working directory under `drafts_dir`."""
    return drafts_dir(settings, session_id) / story_name


def story_final_dir(settings: Settings, session_id: str, story_name: str) -> Path:
    """The story's promoted directory under `stories_dir`."""
    return stories_dir(settings, session_id) / story_name


def _dir_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {entry.name for entry in directory.iterdir() if entry.is_dir()}


def existing_story_names(settings: Settings, session_id: str) -> set[str]:
    """Every story name already claimed in this session, promoted or not.

    Passed into each per-story instruction so the model never reuses a
    name already used by an earlier story in the same batch run.
    """
    return _dir_names(drafts_dir(settings, session_id)) | _dir_names(
        stories_dir(settings, session_id)
    )


def promoted_story_count(settings: Settings, session_id: str) -> int:
    """How many stories have actually been promoted to `docs/stories/`.

    This is the ground truth `batch_cli`'s main loop checks against
    `--count` — it never trusts the agent's own claim of success, only
    what's actually on disk.
    """
    return len(_dir_names(stories_dir(settings, session_id)))


def promote_story(settings: Settings, session_id: str, story_name: str) -> Path:
    """Copy a finished story's draft directory to its final location.

    Raises `FileNotFoundError` if the draft directory doesn't exist, and
    `FileExistsError` if the final directory already exists (promotion
    should only ever happen once per story name).
    """
    draft = story_draft_dir(settings, session_id, story_name)
    if not draft.is_dir():
        raise FileNotFoundError(f"No draft directory for story {story_name!r}: {draft}")
    final = story_final_dir(settings, session_id, story_name)
    shutil.copytree(draft, final)
    return final
