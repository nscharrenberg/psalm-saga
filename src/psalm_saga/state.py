from typing import NotRequired

from deepagents.graph import DeepAgentState


class SageState(DeepAgentState):
    """Extra, run-scoped fields available to every node in the graph."""

    mode: NotRequired[str]
    """"from_scratch" or "from_source" -- mirrors GenerationMode"""

    session_id: NotRequired[str]
    """Directory name of the session under the configured sessions_root."""