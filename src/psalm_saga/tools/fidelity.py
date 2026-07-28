"""Deterministic fidelity check: did the story actually land where the divergence plan intended?

`docs/design.md` flags the risk this closes: an editor subagent that merely *claims* "yes, I
diverged the plot enough" is trusting the model's self-report, and a wrong self-report silently
corrupts a benchmarking dataset's ground-truth labels. This tool computes the comparison itself
from ``story_bible.json``'s ``divergence_plan`` (intended) and ``achieved_divergence`` (the
editor's per-dimension assessment), using :func:`psalm_saga.dimensions.evaluate_fidelity`, so the
mismatch report doesn't depend on the model doing that comparison correctly in its head.
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from psalm_saga.dimensions import StoryBible, evaluate_fidelity


def make_check_fidelity_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a `check_fidelity_alignment` tool bound to one session's bible."""
    bible_path = session_dir / "story_bible.json"

    @tool
    def check_fidelity_alignment() -> str:
        """Compare the divergence plan's intended levels against achieved_divergence.

        Call this after writing achieved_divergence to story_bible.json (from_source mode,
        editor subagent). Reports every dimension where the finished story landed on a different
        similarity level than intended, with a minor/major severity, or confirms full alignment.
        """
        if not bible_path.exists():
            return "No story_bible.json found."

        bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))

        if bible.divergence_plan is None:
            return "No divergence_plan set on this bible -- nothing to check fidelity against."
        if not bible.achieved_divergence:
            return (
                "divergence_plan is set but achieved_divergence is empty. Assess the finished "
                "story against each PSALM dimension and write achieved_divergence before calling "
                "this tool."
            )

        mismatches = evaluate_fidelity(bible.divergence_plan, bible.achieved_divergence)
        if not mismatches:
            return "OK: achieved_divergence matches divergence_plan on every assessed dimension."

        lines = [
            f"- {m.dimension}: intended={m.intended.value}, achieved={m.achieved.value} "
            f"({m.severity})"
            for m in mismatches
        ]
        return "Fidelity mismatches found:\n" + "\n".join(lines)

    return check_fidelity_alignment
