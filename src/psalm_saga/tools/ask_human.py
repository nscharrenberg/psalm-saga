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
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_human(question: str, why: str = "") -> str:
    """Ask the user a single, focused question and wait for their reply.

    Ask ONE question at a time -- do not bundle multiple questions into one call. Prefer
    concrete, answerable questions ("Should the protagonist's rival be a sibling or a mentor?")
    over open-ended ones ("Tell me about your protagonist"), unless the user has signalled they
    want to free-write.

    Args:
        question: The question to show the user, in plain language.
        why: One short sentence on why you're asking (helps the user answer well). Optional.

    Returns:
        The user's raw reply as text.
    """
    payload = {"question": question}
    if why:
        payload["why"] = why
    reply = interrupt(payload)
    return str(reply)
