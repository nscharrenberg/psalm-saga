"""Deterministic, index-addressed chapter file I/O.

Both the orchestrator (composing delegation text) and writer-agent/chapter-reviewer-agent
(reading/writing prose) previously had to construct the exact zero-padded chapter filename
themselves -- and got it wrong: the orchestrator's own delegation text told writer-agent to draft
chapter 1 to `chapters/chapter_1.md` (unpadded), writer-agent wrote there literally, and a later
retry (after `assemble_draft` correctly reported it missing under the padded name) wrote a
*second*, different draft to the correctly-padded `chapters/chapter_01.md` -- leaving two
different stories on disk for the same chapter. These tools remove filename construction from
every agent-facing surface: callers pass the chapter's own `index` integer, never a path.

`CHAPTERS_WRITE_PROTECTION` blocks the generic `write_file`/`edit_file` tools on `chapters/*.md`
(mirroring `BIBLE_WRITE_PROTECTION` in `bible.py`) so writing chapter prose through anything other
than `write_chapter_file` isn't just discouraged, it's unavailable -- a lesson learned from
`chapter_02_revised.md`, an orphaned file produced when a model, told only to prefer one tool over
another, used the other one anyway.
"""

from pathlib import Path

from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.tools import tool

from psalm_saga.tools._chapter_paths import CHAPTERS_DIRNAME, chapter_filename

CHAPTERS_WRITE_PROTECTION: list[FilesystemPermission] = [
    FilesystemPermission(operations=["write"], paths=[f"/{CHAPTERS_DIRNAME}/*.md"], mode="deny"),
]
"""Blocks the built-in `write_file`/`edit_file` tools on `chapters/*.md`. Reading is unaffected --
only writing chapter prose through anything but `write_chapter_file` is blocked."""


def make_write_chapter_file_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a `write_chapter_file` tool bound to one session's chapters directory."""
    chapters_dir = session_dir / CHAPTERS_DIRNAME

    @tool
    def write_chapter_file(index: int, content: str) -> str:
        """Write (or overwrite) one chapter's prose, addressed by its `index` -- never a filename.

        This is always the single correct destination for that chapter index. Overwrites
        unconditionally -- no "already exists" refusal, and no need to choose between writing and
        editing -- so a revision pass always lands in the same place the first draft did.

        Args:
            index: The chapter's own `index` field from story_bible.json's `chapters` list.
            content: The finished chapter prose.
        """
        chapters_dir.mkdir(parents=True, exist_ok=True)
        name = chapter_filename(index)
        path = chapters_dir / name
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        verb = "Overwrote" if existed else "Wrote"
        return f"OK: {verb} {CHAPTERS_DIRNAME}/{name} ({len(content)} characters)."

    return write_chapter_file


def make_read_chapter_file_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a `read_chapter_file` tool bound to one session's chapters directory."""
    chapters_dir = session_dir / CHAPTERS_DIRNAME

    @tool
    def read_chapter_file(index: int) -> str:
        """Read one chapter's prose, addressed by its `index` -- never a filename.

        Args:
            index: The chapter's own `index` field from story_bible.json's `chapters` list.
        """
        name = chapter_filename(index)
        path = chapters_dir / name
        if not path.exists():
            return (
                f"Chapter {index} has not been written yet "
                f"(no file at {CHAPTERS_DIRNAME}/{name})."
            )
        return path.read_text(encoding="utf-8")

    return read_chapter_file
