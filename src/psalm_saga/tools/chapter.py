"""Deterministic, index-addressed chapter updates.

`update_story_bible` (RFC 6902 patches against raw array positions) requires the caller to
compute `array_position = chapter.index - 1` correctly on every call -- and, in production,
different agents got this arithmetic wrong in different ways within the same session:
`chapter-reviewer-agent` repeatedly targeted the wrong position reviewing chapter 2, and when its
own `test`-op guard caught the mismatch, it "fixed" the failure by force-overwriting the guarded
`index` field instead of recomputing its position -- turning chapter 3 into a second chapter 2
and silently corrupting the whole chapter list (two entries with `index=2`, none with `index=3`).
This tool removes the array-position arithmetic from the agent-facing surface entirely: callers
address a chapter by its own `index` field, and the lookup happens here, deterministically.
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from psalm_saga.dimensions import ChapterStatus, StoryBible


def make_update_chapter_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build an `update_chapter` tool bound to one session's bible."""
    bible_path = session_dir / "story_bible.json"

    @tool
    def update_chapter(
        index: int,
        status: ChapterStatus | None = None,
        actual_summary: str | None = None,
        increment_revision_count: bool = False,
    ) -> str:
        """Update one chapter, found by its `index` field -- never by array position.

        Only the fields you pass are changed; everything else on the chapter is left exactly as
        it was. Use this instead of hand-writing an `update_story_bible` patch against
        `/chapters/<n>/...` for status/actual_summary/revision_count -- you would have to compute
        which array position `index` currently lives at, and getting that wrong silently corrupts
        a different chapter.

        Args:
            index: The chapter's own `index` field (1-based, matching its outline entry) -- not
                a position in the `chapters` list.
            status: New status ("planned"/"drafted"/"approved"), if changing it.
            actual_summary: New actual_summary text, if setting/updating it.
            increment_revision_count: If True, bump the chapter's revision_count by 1 from
                whatever it currently is -- you never need to know or pass the current count.
        """
        if not bible_path.exists():
            return "Cannot update chapter -- story_bible.json does not exist yet."

        bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))

        matches = [i for i, c in enumerate(bible.chapters) if c.index == index]
        if not matches:
            existing = ", ".join(str(c.index) for c in bible.chapters) or "none"
            return f"No chapter with index={index} found. Existing chapter indices: {existing}."
        if len(matches) > 1:
            return (
                f"Multiple chapters share index={index} -- story_bible.json's chapters list is "
                "corrupt (this should be unreachable). Refusing to update ambiguously; fix the "
                "duplicate index by hand via update_story_bible before retrying."
            )

        chapter = bible.chapters[matches[0]]
        if status is not None:
            chapter.status = status
        if actual_summary is not None:
            chapter.actual_summary = actual_summary
        if increment_revision_count:
            chapter.revision_count += 1

        bible_path.write_text(bible.model_dump_json(indent=2), encoding="utf-8")
        return f"OK: chapter index={index} updated (status={chapter.status.value})."

    return update_chapter
