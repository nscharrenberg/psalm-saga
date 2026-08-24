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
