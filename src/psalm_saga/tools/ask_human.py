"""The human-in-the-loop question tool.

Brainstorming is conversational: the agent decides what to ask next, one question at a time,
based on what's already in the bible. Because ``create_deep_agent`` compiles to a LangGraph
graph, the right primitive for "pause and wait for a human" is ``langgraph.types.interrupt`` --
*not* a blocking ``input()`` call inside the tool, which would freeze the whole process and
doesn't generalize beyond a local CLI.

Calling ``ask_human`` raises a ``GraphInterrupt`` that unwinds execution back to whoever called
``.invoke()``/``.stream()`` with a checkpointer configured. That caller (today: the CLI driver in
``cli.py``; tomorrow: a web backend) is responsible for surfacing the question, collecting an
answer, and resuming the graph with ``Command(resume=answer)``. This keeps the tool itself
transport-agnostic, which is what makes it reusable outside the CLI.

**Non-interactive / batch sessions** (see ``batch.py``) have no human to interrupt for -- a real
``interrupt()`` there would just hang forever, since nothing is driving the resume side. Rather
than let that happen silently, :func:`make_ask_human_tool` builds a variant that short-circuits:
it never pauses the graph, and instead returns a message telling the agent no human is available
and it must make and record its own reasonable default. This is a deliberate no-op, not a bug --
subagent prompts (see ``prompts/brainstorm.md``) are written to expect and handle this reply.
"""

from __future__ import annotations

from langchain_core.tools import tool
from langgraph.types import interrupt

NON_INTERACTIVE_REPLY = (
    "NO_HUMAN_AVAILABLE: this is a non-interactive session (e.g. a batch dataset-generation run). "
    "There is no user to answer questions. Make a specific, reasonable decision yourself for "
    "whatever you were about to ask, record it in story_bible.json as settled, note the "
    "assumption in your final message, and continue -- do not call ask_human again for this."
)


def make_ask_human_tool(*, non_interactive: bool = False):  # type: ignore[no-untyped-def]
    """Build the `ask_human` tool for one session.

    Args:
        non_interactive: If True, the tool never actually interrupts the graph -- it immediately
            returns :data:`NON_INTERACTIVE_REPLY` instead. Use for batch/unattended sessions.
    """

    @tool
    def ask_human(question: str, why: str = "") -> str:
        """Ask the user a single, focused question and wait for their reply.

        Ask ONE question at a time -- do not bundle multiple questions into one call. Prefer
        concrete, answerable questions ("Should the protagonist's rival be a sibling or a
        mentor?") over open-ended ones ("Tell me about your protagonist"), unless the user has
        signalled they want to free-write.

        In a non-interactive/batch session, this returns immediately with a note that no human
        is available instead of pausing -- treat that as a signal to decide for yourself.

        Args:
            question: The question to show the user, in plain language.
            why: One short sentence on why you're asking (helps the user answer well). Optional.

        Returns:
            The user's raw reply as text, or a non-interactive-mode notice.
        """
        if non_interactive:
            return NON_INTERACTIVE_REPLY

        payload = {"question": question}
        if why:
            payload["why"] = why
        reply = interrupt(payload)
        return str(reply)

    return ask_human