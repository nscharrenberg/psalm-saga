"""Deterministic enforcement of the originality-guard strictness setting.

`docs/design.md` flagged that `block` vs `warn` strictness was, in the first pass, only a system
prompt instruction to the orchestrator -- a strong nudge, not a hard invariant. This module turns
the check itself into a deterministic tool: the orchestrator's prompt requires calling it before
delegating to `writer-agent`, and it returns an unambiguous PROCEED/BLOCKED verdict computed from
the bible's actual `originality_findings`, not from the model's judgment of its own findings.

This still isn't a graph-level hard gate (deepagents does not expose a clean hook to veto a
specific subagent name from outside the graph without subclassing `SubAgentMiddleware`/the `task`
tool internals), so a model that ignores its instructions could still call `task(subagent="writer-
agent", ...)` after a BLOCKED verdict. What this buys us over the prompt-only version: the
blocking decision no longer depends on the model correctly counting/reasoning about findings
itself, only on it calling one tool and respecting a literal string result -- a much smaller
surface for the model to get wrong, and one that's easy to unit test (see
`tests/test_gate_tool.py`) independent of any live model call.
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from psalm_saga.config import GuardStrictness
from psalm_saga.dimensions import StoryBible


def make_check_originality_gate_tool(session_dir: Path, strictness: GuardStrictness):  # type: ignore[no-untyped-def]
    """Build a `check_originality_gate` tool bound to one session's bible and configured strictness."""
    bible_path = session_dir / "story_bible.json"

    @tool
    def check_originality_gate() -> str:
        """Check whether it's OK to delegate to writer-agent yet (from_scratch mode).

        Call this after the originality-guard subagent has run (and after any revision loop),
        before delegating to writer-agent. Do not delegate to writer-agent if this returns
        BLOCKED -- surface the open findings to the user and ask how they want to proceed instead.
        """
        if not bible_path.exists():
            return "BLOCKED: story_bible.json does not exist yet."

        try:
            bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the model, deliberately broad
            return f"BLOCKED: story_bible.json is not currently valid ({exc}). Fix it first."

        open_findings = [f for f in bible.originality_findings if not f.resolved]
        if not open_findings:
            return "PROCEED: no open originality findings."

        summary = "; ".join(f"[{f.category}] {f.description}" for f in open_findings)

        if strictness is GuardStrictness.WARN:
            return (
                f"PROCEED (with {len(open_findings)} unresolved finding(s), strictness=warn): "
                f"{summary}. Make sure your final report to the user surfaces these clearly."
            )

        return (
            f"BLOCKED (strictness=block): {len(open_findings)} unresolved originality "
            f"finding(s): {summary}. Send the bible back to brainstorm-agent to address them, "
            "or stop and ask the user to explicitly override before proceeding to writer-agent."
        )

    return check_originality_gate
