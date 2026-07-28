from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from psalm_saga.agents.subagents import build_subagents
from psalm_saga.config import Settings
from psalm_saga.prompts import load_prompt
from psalm_saga.state import SagaState
from psalm_saga.tools import make_validate_bible_tool, think


def build_orchestrator(  # type: ignore[no-untyped-def]
        settings: Settings,
        session_dir: Path,
        checkpointer: BaseCheckpointSaver  # type: ignore[type-arg]
):
    """
    Builds and initializes the orchestrator, a deep agent responsible for managing
    subagents and tools while maintaining a scalable backend. This orchestrator is
    designed for handling complex workflows based on the provided settings.

    :param settings: Configuration settings for the orchestrator.
    :type settings: Settings
    :param session_dir: Path to the directory where the session files are stored.
    :type session_dir: Path
    :param checkpointer: An instance of BaseCheckpointSaver that handles saving
        and restoring checkpoints for the orchestrator's state.
    :type checkpointer: BaseCheckpointSaver
    :return: The initialized deep agent orchestrator.
    :rtype: Any
    """
    backend = FilesystemBackend(root_dir=str(session_dir), virtual_mode=True)
    subagents = build_subagents(settings, session_dir)
    validate_story_bible = make_validate_bible_tool(session_dir)

    return create_deep_agent(
        model=settings.model,
        system_prompt=load_prompt("orchestrator"),
        tools=[think, validate_story_bible],
        subagents=subagents,
        backend=backend,
        state_schema=SagaState,
        checkpointer=checkpointer,
        name="psalm-saga-orchestrator"
    )