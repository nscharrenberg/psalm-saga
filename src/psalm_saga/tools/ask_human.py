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

#: `ask_human` always returns a plain string, so "the user wants to keep discussing this, not
#: answer it" has to be signalled in-band. This prefix is self-describing on purpose -- the agent
#: doesn't need to memorize a magic constant, the text itself explains what to do. Mirrors
#: `NON_INTERACTIVE_REPLY` above, the existing convention for out-of-band signals in this tool.
STILL_EXPLORING_PREFIX = (
    "STILL_EXPLORING (this is not a final answer -- the user wants to discuss this specific "
    "question further before deciding; respond conversationally and keep exploring it with "
    "them, don't record anything as settled yet): "
)


def format_discussion_reply(text: str) -> str:
    """Wrap a reply that means "let's discuss this more," not a settled answer.

    Called by the transport layer (e.g. the CLI) when the user chooses to discuss a question
    further instead of answering it, so the resulting tool output self-describes what kind of
    reply this is.
    """
    return f"{STILL_EXPLORING_PREFIX}{text}"


def make_ask_human_tool(*, non_interactive: bool = False):  # type: ignore[no-untyped-def]
    """Build the `ask_human` tool for one session.

    Args:
        non_interactive: If True, the tool never actually interrupts the graph -- it immediately
            returns :data:`NON_INTERACTIVE_REPLY` instead. Use for batch/unattended sessions.
    """

    @tool
    def ask_human(question: str, options: list[str] | None = None, why: str = "") -> str:
        """Ask the user a single, focused question and wait for their reply.

        Ask ONE question at a time -- do not bundle multiple questions into one call. Prefer
        concrete, answerable questions ("Should the protagonist's rival be a sibling or a
        mentor?") over open-ended ones ("Tell me about your protagonist"), unless the user has
        signalled they want to free-write.

        In a non-interactive/batch session, this returns immediately with a note that no human
        is available instead of pausing -- treat that as a signal to decide for yourself.

        Args:
            question: The question to show the user, in plain language.
            options: 2-4 short, concrete, mutually exclusive directions the user can pick from
                (e.g. ["A harbor official who wants the letters stopped", "His own daughter,
                scared of what he's becoming"]). Supply this whenever you have specific
                proposals in mind -- which is most of the time. Leave it unset only for
                genuinely open questions. The user will always also be able to write their own
                answer or ask to discuss the question further, so don't add filler options like
                "something else" yourself -- only list substantive proposals.
            why: One short sentence on why you're asking (helps the user answer well). Optional.

        Returns:
            The user's raw reply as text if they picked or wrote an answer. If they chose to
            discuss the question further instead, the reply is prefixed with "STILL_EXPLORING"
            -- treat that as a cue to keep the conversation going on this specific question (ask
            a follow-up, riff, offer new options) rather than recording anything as settled.
        """
        if non_interactive:
            return NON_INTERACTIVE_REPLY

        payload: dict[str, str | list[str]] = {"question": question}
        if why:
            payload["why"] = why
        if options:
            payload["options"] = options
        reply = interrupt(payload)
        return str(reply)

    return ask_human
