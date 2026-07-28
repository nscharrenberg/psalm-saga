from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.base import BaseCheckpointSaver

from psalm_saga.agents.subagents import build_subagents
from psalm_saga.config import Settings
from psalm_saga.prompts import load_prompt
from psalm_saga.state import SagaState
from psalm_saga.tools import make_validate_bible_tool, think, make_check_originality_gate_tool, \
    make_check_fidelity_tool, make_update_story_bible_tool


def build_orchestrator(  # type: ignore[no-untyped-def]
        settings: Settings,
        session_dir: Path,
        checkpointer: BaseCheckpointSaver,  # type: ignore[type-arg]
        *,
        non_interactive: bool = False,
):
    """
    Builds and initializes the orchestrator agent for managing the saga system.

    This function sets up the backend, tools, subagents, and the main agent
    required for the orchestrator's workflow. It integrates various components
    to ensure a coherent and functional system capable of performing tasks
    like validation, originality checking, and deep agent functionality.

    :param settings: Configuration object containing the settings for the
        orchestrator.
    :type settings: Settings
    :param session_dir: Path to the session directory for storing files and
        managing session-specific data.
    :type session_dir: Path
    :param checkpointer: Checkpoint saver for handling state persistence
        during the orchestrator's operation.
    :type checkpointer: BaseCheckpointSaver
    :param non_interactive: If True, the orchestrator will operate
        in non-interactive mode.
    :type non_interactive: bool
    :return: Initialized deep agent orchestrator.
    :rtype: DeepAgent
    """
    backend = FilesystemBackend(root_dir=str(session_dir), virtual_mode=True)
    subagents = build_subagents(settings, session_dir, non_interactive=non_interactive)
    update_story_bible = make_update_story_bible_tool(session_dir)
    validate_story_bible = make_validate_bible_tool(session_dir)
    check_originality_gate = make_check_originality_gate_tool(
        session_dir,
        settings.originality_guard_strictness
    )
    check_fidelity_alignment = make_check_fidelity_tool(session_dir)

    return create_deep_agent(
        model=settings.model,
        system_prompt=load_prompt("orchestrator"),
        tools=[think, update_story_bible, validate_story_bible, check_originality_gate, check_fidelity_alignment],
        subagents=subagents,
        backend=backend,
        state_schema=SagaState,
        checkpointer=checkpointer,
        name="psalm-saga-orchestrator"
    )
