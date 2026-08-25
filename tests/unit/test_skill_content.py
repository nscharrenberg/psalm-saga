"""Lightweight regression checks that the batch-mode "Autonomous Mode"
sections added to the interactive skills are actually present on disk.
Not a substitute for the eval-based behavioral checks in tests/evals/ —
just a guard against a section being accidentally deleted or renamed.
"""

from __future__ import annotations

from psalm_saga.bootstrap import SKILLS_DIR


def _read_skill(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def test_story_brainstorming_has_autonomous_mode_section() -> None:
    body = _read_skill("story-brainstorming")

    assert "## Autonomous Mode" in body
    assert "docs/drafts/<story_name>/<story_name>-spec.md" in body


def test_writing_story_plans_has_autonomous_mode_section() -> None:
    body = _read_skill("writing-story-plans")

    assert "## Autonomous Mode" in body
    assert "docs/drafts/<story_name>/<story_name>-plan.md" in body


def test_reviewing_story_dimensions_has_autonomous_mode_section() -> None:
    body = _read_skill("reviewing-story-dimensions")

    assert "## Autonomous Mode" in body
    assert "ABANDONED.md" in body


def test_length_and_chapters_reference_exists_with_full_taxonomy() -> None:
    reference = (
        SKILLS_DIR / "story-brainstorming" / "references" / "length-and-chapters.md"
    ).read_text(encoding="utf-8")

    for label in ("Drabble", "Flash Fiction", "Short Story", "Novelette", "Novella", "Novel", "Epic"):
        assert label in reference
    assert "1,500" in reference  # the ~1,500-5,000 words/chapter novel norm
    assert "auto" in reference.lower()


def test_story_brainstorming_treats_a_length_directive_as_locked() -> None:
    body = _read_skill("story-brainstorming")

    assert "length-and-chapters.md" in body
    assert "length directive" in body.lower()
