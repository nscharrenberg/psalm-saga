"""Single source of truth for the on-disk chapter-file naming convention.

Shared by `assemble.py` (which reads chapter files to build `draft.md`) and `chapter_files.py`
(which reads/writes them on behalf of writer-agent/chapter-reviewer-agent) so the convention can
never drift between the two -- see the chapter-by-chapter generation design.
"""

CHAPTERS_DIRNAME = "chapters"


def chapter_filename(index: int) -> str:
    return f"chapter_{index:02d}.md"
