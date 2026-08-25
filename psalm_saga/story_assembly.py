"""Assembling a batch story's draft directory into the single reader-facing
file `psalm-saga-batch` promotes to `docs/stories/`.

A draft directory holds the working documents a story's pipeline needed —
`<story_name>-spec.md`, `<story_name>-plan.md`, `<story_name>-review.md`,
per-chapter files, and a `DONE.md`/`ABANDONED.md` marker. None of that is
what a reader wants: a reader gets one file, a title, and the chapters in
order. This module builds exactly that from the plan (for the title) and
the `chapter-<N>-<slug>.md` files `drafting-chapters`' Autonomous Mode
section pins down (for the prose).
"""

from __future__ import annotations

import re
from pathlib import Path

_CHAPTER_FILENAME_RE = re.compile(r"^chapter-(\d+)-")
_TITLE_HEADING_RE = re.compile(r"^#\s+(.+?)\s*[—-]\s*Story Plan\s*$", re.MULTILINE)


def extract_title(plan_text: str, *, fallback: str) -> str:
    """Pull the story's title out of its plan file's text.

    `writing-story-plans`' Autonomous Mode section documents the plan's
    own first line as `# <Title> — Story Plan`. Falls back to `fallback`
    (title-cased from the story's own kebab-case name) if that heading
    isn't found, rather than ever failing promotion over a title-parsing
    miss.
    """
    match = _TITLE_HEADING_RE.search(plan_text)
    if match:
        return match.group(1).strip()
    return fallback.replace("-", " ").title()


def find_chapter_files(draft_dir: Path) -> list[Path]:
    """Every `chapter-<N>-*.md` file in `draft_dir`, sorted by `<N>`.

    Sorted numerically (not lexically), so `chapter-10-...` sorts after
    `chapter-9-...` rather than before `chapter-2-...`. Any other file in
    the draft directory (spec, plan, review, `DONE.md`, `ABANDONED.md`) is
    ignored — only files matching the pinned chapter naming convention
    count.
    """
    chapters: list[tuple[int, Path]] = []
    for path in draft_dir.iterdir():
        if not path.is_file():
            continue
        match = _CHAPTER_FILENAME_RE.match(path.name)
        if match:
            chapters.append((int(match.group(1)), path))
    chapters.sort(key=lambda pair: pair[0])
    return [path for _, path in chapters]


def _demote_leading_heading(chapter_text: str) -> str:
    """Demote a chapter's own top-level `# ` heading to `##`.

    Chapter files are written as standalone documents, each with its own
    `# Chapter <N>: <Title>` (H1) heading. Folded into the assembled book
    unchanged, that would put every chapter heading at the same level as
    the book's own title. Demoting it one level keeps the book title the
    document's only H1. A chapter with no leading `# ` heading is left
    untouched rather than guessed at.
    """
    if chapter_text.startswith("# "):
        return "#" + chapter_text
    return chapter_text


def assemble_story(draft_dir: Path, story_name: str) -> str:
    """Build the single reader-facing Markdown document for one story.

    Reads `<story_name>-plan.md` for the title (falling back to
    `story_name` if the plan is missing or its title heading isn't
    found) and every `chapter-<N>-*.md` file, in chapter order, for the
    prose — each chapter's own leading heading demoted to `##` so the
    book title is the document's only `#`.

    Raises `ValueError` if no chapter files are found — an empty "story"
    is a defect to surface, not something to promote silently.
    """
    plan_path = draft_dir / f"{story_name}-plan.md"
    if plan_path.is_file():
        title = extract_title(plan_path.read_text(encoding="utf-8"), fallback=story_name)
    else:
        title = story_name.replace("-", " ").title()

    chapter_files = find_chapter_files(draft_dir)
    if not chapter_files:
        raise ValueError(f"No chapter files found in {draft_dir}")

    chapters_text = "\n\n".join(
        _demote_leading_heading(path.read_text(encoding="utf-8").strip())
        for path in chapter_files
    )
    return f"# {title}\n\n{chapters_text}\n"
