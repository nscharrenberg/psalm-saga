"""A no-op reflection tool.

This mirrors the ``think_tool`` popularized by LangChain's open_deep_research: it gives the
model an explicit, logged place to reason about a decision (is this bible field settled? does
this scene resemble a known work? is the brainstorming conversation converging?) before it takes
an action, without that reasoning leaking into the final story text. The tool does no work; its
only effect is to appear in the transcript as a discrete, inspectable step.
"""

from langchain_core.tools import tool


@tool
def think(thought: str) -> str:
    """Record a private reasoning step before taking your next action.

    Use this before: deciding what to ask the user next, judging whether a bible dimension is
    settled enough to move on, evaluating an originality concern, or checking your own output
    against the requirements. Not shown to the user -- it is your scratchpad, not the deliverable.

    Args:
        thought: Your reasoning, written out in full rather than summarized.
    """
    return f"Recorded reasoning ({len(thought)} chars)."
