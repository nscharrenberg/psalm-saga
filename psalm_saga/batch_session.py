"""Directory layout, name bookkeeping, and promotion logic for
`psalm-saga-batch` sessions.

Batch sessions use `docs/drafts/<story_name>/` for work in progress —
spec, plan, review, per-chapter files, and a `DONE.md`/`ABANDONED.md`
marker — and a single `docs/stories/<story_name>.md` file for a finished
story, instead of interactive sessions' `docs/psalm-saga/<slug>-*.md`
convention. A promoted story is not a copy of the draft directory: it's
the title and chapters only, assembled by `psalm_saga.story_assembly`, the
way a reader gets the finished book rather than the working documents.
Every function here takes the same `(settings, session_id)` pair
`psalm_saga.session` uses, so a batch session is just a normal session
with a different `docs/` shape.
"""

from __future__ import annotations

from pathlib import Path

from psalm_saga.session import session_directory
from psalm_saga.settings import Settings
from psalm_saga.story_assembly import assemble_story

DRAFTS_DIRNAME = "drafts"
STORIES_DIRNAME = "stories"
DOCS_DIRNAME = "docs"
STORY_FILE_SUFFIX = ".md"


def drafts_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/drafts/` — every story's working directory."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / DRAFTS_DIRNAME


def stories_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/stories/` — every finished story."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / STORIES_DIRNAME


def story_draft_dir(settings: Settings, session_id: str, story_name: str) -> Path:
    """The story's working directory under `drafts_dir`."""
    return drafts_dir(settings, session_id) / story_name


def story_final_path(settings: Settings, session_id: str, story_name: str) -> Path:
    """The story's promoted single-file location under `stories_dir`."""
    return stories_dir(settings, session_id) / f"{story_name}{STORY_FILE_SUFFIX}"


def _dir_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {entry.name for entry in directory.iterdir() if entry.is_dir()}


def promoted_story_names(settings: Settings, session_id: str) -> set[str]:
    """Every story name already promoted to `docs/stories/`."""
    stories = stories_dir(settings, session_id)
    if not stories.is_dir():
        return set()
    return {
        entry.stem
        for entry in stories.iterdir()
        if entry.is_file() and entry.suffix == STORY_FILE_SUFFIX
    }


def existing_story_names(settings: Settings, session_id: str) -> set[str]:
    """Every story name already claimed in this session, promoted or not.

    Passed into each per-story instruction so the model never reuses a
    name already used by an earlier story in the same batch run.
    """
    return _dir_names(drafts_dir(settings, session_id)) | promoted_story_names(
        settings, session_id
    )


def promoted_story_count(settings: Settings, session_id: str) -> int:
    """How many stories have actually been promoted to `docs/stories/`.

    This is the ground truth `batch_cli`'s main loop checks against
    `--count` — it never trusts the agent's own claim of success, only
    what's actually on disk.
    """
    return len(promoted_story_names(settings, session_id))


def promote_story(settings: Settings, session_id: str, story_name: str) -> Path:
    """Assemble a finished story's chapters into a single reader-facing file.

    Reads the draft's plan (for the title) and chapter files (for the
    prose, in order) via `story_assembly.assemble_story`, and writes the
    result to `docs/stories/<story_name>.md` — not a copy of the whole
    draft directory. The working documents (spec, plan, review, `DONE.md`)
    stay in the draft directory as the audit trail; they're never
    promoted.

    Raises `FileNotFoundError` if the draft directory doesn't exist, and
    `FileExistsError` if the final file already exists (promotion should
    only ever happen once per story name).
    """
    draft = story_draft_dir(settings, session_id, story_name)
    if not draft.is_dir():
        raise FileNotFoundError(f"No draft directory for story {story_name!r}: {draft}")
    final = story_final_path(settings, session_id, story_name)
    if final.exists():
        raise FileExistsError(f"Story already promoted: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_text(assemble_story(draft, story_name), encoding="utf-8")
    return final
