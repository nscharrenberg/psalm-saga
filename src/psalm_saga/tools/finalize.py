"""Deterministic seeding of final_story.md from draft.md.

`editor-agent` used to be told to "produce the final version" of the whole book in one
`write_file` call -- which, for a real multi-chapter book, means regenerating the entire text
from scratch in a single completion. In production this silently truncated a 6-chapter,
~25,000-character `draft.md` to a ~10,000-character `final_story.md` (3 chapters) with no error:
the model simply stopped partway through, the same failure category the chapter-by-chapter
rewrite of `writer-agent` was built to fix, just never migrated on the editor side.

`finalize_story` closes that gap the same way `assemble_draft` closed the writer-side one: it is
called once, deterministically, by the orchestrator *before* delegating to `editor-agent`, so
`final_story.md` is always a complete, correct copy of every chapter regardless of what
editor-agent does afterward. editor-agent's job becomes reading what's already there and making
only targeted `edit_file` fixes for specific issues it finds -- never a full rewrite.
"""

from pathlib import Path

from langchain_core.tools import tool


def make_finalize_story_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a `finalize_story` tool bound to one session's draft/final-story files."""
    draft_path = session_dir / "draft.md"
    final_path = session_dir / "final_story.md"

    @tool
    def finalize_story() -> str:
        """Copy draft.md to final_story.md verbatim.

        Call this once, right before delegating to editor-agent -- it guarantees final_story.md
        starts as a complete, correct copy of every chapter, so editor-agent only ever needs to
        edit specific passages it finds issues with, never regenerate the whole book from
        scratch. Safe to call again (e.g. on a resumed session): it always resets final_story.md
        to match the current draft.md, discarding anything from a previous attempt.
        """
        if not draft_path.exists():
            return "Cannot finalize -- draft.md does not exist yet. Run assemble_draft first."

        final_path.write_text(draft_path.read_text(encoding="utf-8"), encoding="utf-8")
        return "OK: final_story.md initialized as a copy of draft.md."

    return finalize_story
