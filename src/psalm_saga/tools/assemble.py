"""Deterministic assembly of the per-chapter drafts into draft.md.

`writer-agent` drafts one chapter at a time to `chapters/chapter_<NN>.md` rather than the whole
book in one file (see the chapter-by-chapter generation design). This tool is the deterministic
seam between that per-chapter loop and `editor-agent`'s existing whole-book pass: it concatenates
every approved chapter into `draft.md` exactly once, so `editor-agent` keeps reading a single
assembled file the same way it always has. It is wired into the orchestrator's own tool list
(`agents/orchestrator.py`), not given to any subagent -- assembling the book is sequencing work,
the same role `check_originality_gate`/`check_fidelity_alignment` already play.
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from psalm_saga.dimensions import ChapterStatus, StoryBible

CHAPTERS_DIRNAME = "chapters"


def _chapter_filename(index: int) -> str:
    return f"chapter_{index:02d}.md"


def make_assemble_draft_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build an `assemble_draft` tool bound to one session's bible and chapters directory."""
    bible_path = session_dir / "story_bible.json"
    chapters_dir = session_dir / CHAPTERS_DIRNAME

    @tool
    def assemble_draft(include_unapproved: bool = False) -> str:
        """Concatenate every approved chapter into draft.md, in chapter order.

        Call this once every chapter in story_bible.json's `chapters` list has status=approved.
        Refuses, naming the offending chapter(s), if any chapter isn't approved yet, or if an
        approved chapter's file is unexpectedly missing from chapters/ -- draft.md is only written
        once every chapter is genuinely ready for editor-agent to read.

        :param include_unapproved: Default False, which preserves the refuse-on-any-non-approved
            behavior above. Set True as the escape hatch for a chapter that exhausted its revision
            budget without reaching approved: every chapter is included regardless of status (still
            sorted by index, still read from its file on disk if present), and the refusal only
            fires if a chapter's file is genuinely missing from chapters/ -- there is nothing to
            read for that chapter. When some included chapters were not approved, the success
            message names them explicitly (e.g. "included despite status=drafted: chapter 7").
        """
        if not bible_path.exists():
            return "Cannot assemble draft.md -- story_bible.json does not exist yet."

        bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))

        if not bible.chapters:
            return (
                "Cannot assemble draft.md -- story_bible.json has no chapters yet. Run "
                "chapter-planner-agent first."
            )

        seen_indices: dict[int, int] = {}
        for chapter in bible.chapters:
            seen_indices[chapter.index] = seen_indices.get(chapter.index, 0) + 1
        duplicates = sorted(index for index, count in seen_indices.items() if count > 1)
        if duplicates:
            return (
                "Cannot assemble draft.md -- story_bible.json's chapters list has duplicate "
                f"index value(s): {', '.join(str(i) for i in duplicates)}. Fix the corrupt "
                "entry (via update_story_bible) before assembling."
            )

        not_approved = [c for c in bible.chapters if c.status is not ChapterStatus.APPROVED]
        if not_approved and not include_unapproved:
            names = ", ".join(f"chapter {c.index} ({c.status.value})" for c in not_approved)
            return f"Cannot assemble draft.md -- not every chapter is approved yet: {names}."

        ordered = sorted(bible.chapters, key=lambda c: c.index)

        missing: list[str] = []
        bodies: list[str] = []
        for chapter in ordered:
            chapter_path = chapters_dir / _chapter_filename(chapter.index)
            if not chapter_path.exists():
                missing.append(f"chapter {chapter.index} ({_chapter_filename(chapter.index)})")
                continue
            heading = chapter.title or f"Chapter {chapter.index}"
            bodies.append(f"## {heading}\n\n{chapter_path.read_text(encoding='utf-8').strip()}")

        if missing:
            reason = (
                "required but their files are"
                if include_unapproved
                else "approved but their files are"
            )
            return (
                f"Cannot assemble draft.md -- these chapters are {reason} "
                f"missing from {CHAPTERS_DIRNAME}/: " + ", ".join(missing)
            )

        title = bible.title or "Untitled"
        draft = f"# {title}\n\n" + "\n\n".join(bodies) + "\n"
        (session_dir / "draft.md").write_text(draft, encoding="utf-8")

        message = f"OK: draft.md assembled from {len(ordered)} chapter(s)."
        if include_unapproved and not_approved:
            names = ", ".join(f"chapter {c.index} (status={c.status.value})" for c in not_approved)
            message += f" Included despite non-approved status: {names}."
        return message

    return assemble_draft
