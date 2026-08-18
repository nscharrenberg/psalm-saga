"""Wires the psalm-saga deep agent into DeepEval's multi-turn simulator.

`ConversationSimulator` mints one `thread_id` per simulated conversation and
passes it to `chatbot_callback` on every turn (see
`deepeval.simulator.conversation_simulator.ConversationSimulator`). Turns
within one conversation must resume the same underlying agent and its
checkpointer, so the compiled agent is cached per `thread_id` here rather
than rebuilt on every call.

Eval runs get their own session backend root (`.runtime/`, gitignored)
instead of the developer's own `my-story/` sessions, so eval traffic never
mixes with real story sessions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepeval.integrations.langchain import CallbackHandler
from deepeval.test_case import Turn
from dotenv import load_dotenv

from psalm_saga.agent import build_agent
from psalm_saga.settings import Settings

load_dotenv()

EVAL_ROOT_DIR = Path(__file__).resolve().parent / ".runtime"

CHATBOT_ROLE = (
    "A spec-first story-writing assistant. It elicits the user's explicit "
    "choices across all six PSALM dimensions (writing style, narrative "
    "voice, character, plot structure, scene sequence, world-building) into "
    "a written spec, gets the user's sign-off on that spec, then carries it "
    "into a plan and dispatches chapter drafting and dimension review to "
    "named subagents. It never drafts story prose before the spec is "
    "signed off."
)

_agents: dict[str, Any] = {}


def _agent_for_thread(thread_id: str) -> Any:
    if thread_id not in _agents:
        settings = Settings(backend={"root_dir": EVAL_ROOT_DIR})
        _agents[thread_id] = build_agent(settings, session_id=thread_id)
    return _agents[thread_id]


def _as_text(content: Any) -> str:
    """Flatten an `AIMessage.content` into plain text.

    With `use_responses_api: true` (this project's default for reasoning
    models — see `settings.py`), `content` is a list of OpenAI Responses API
    content blocks (`type: "reasoning"`, `type: "text"`, ...) rather than a
    plain string; only the `"text"` blocks are the model's visible reply.
    """
    if isinstance(content, str):
        return content
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def chatbot_callback(input: str, thread_id: str) -> Turn:  # noqa: A002
    agent = _agent_for_thread(thread_id)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": input}]},
        config={
            "configurable": {"thread_id": thread_id},
            "callbacks": [CallbackHandler(thread_id=thread_id)],
        },
    )
    content = _as_text(result["messages"][-1].content)
    return Turn(role="assistant", content=content)
