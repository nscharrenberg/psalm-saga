from typing import Annotated, NotRequired

from deepagents.graph import DeepAgentState
from langchain.agents.middleware.types import PrivateStateAttr


class SagaState(DeepAgentState):
    """Extra, run-scoped fields available to every node in the graph.

    Both fields are marked `PrivateStateAttr`: deepagents' task tool otherwise echoes back
    *every* non-excluded state key from a subagent's result via `Command(update=...)`, and
    since neither field has a reducer, two subagent invocations resolving in the same graph
    superstep (e.g. the orchestrator delegating writer-agent for several chapters in one turn)
    crash with `InvalidUpdateError: At key '<field>': Can receive only one value per step` --
    even when both writes are identical. `PrivateStateAttr` keeps these fields out of every
    subagent's input state, so nothing is echoed back to collide on. Nothing in this codebase
    reads either field back out of graph state (they're write-once, at session start).
    """

    mode: NotRequired[Annotated[str, PrivateStateAttr]]
    """"from_scratch" or "from_source" -- mirrors GenerationMode"""

    session_id: NotRequired[Annotated[str, PrivateStateAttr]]
    """Directory name of the session under the configured sessions_root."""