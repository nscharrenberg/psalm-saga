from deepagents.middleware._state import private_state_field_names  # type: ignore[import-untyped]

from psalm_saga.state import SagaState  # type: ignore[import-untyped]


def test_mode_and_session_id_are_private_state_fields() -> None:
    """Regression test for InvalidUpdateError: At key 'mode' -- Can receive only one value per
    step. `mode`/`session_id` have no reducer, so when deepagents' task tool runs multiple
    subagent invocations concurrently (e.g. the orchestrator delegating writer-agent for several
    chapters in one turn), each invocation's Command echoes back whatever state keys the subagent
    ended with, and two concurrent writes to the same unreduced channel crash the run -- even
    though nothing ever reads mode/session_id back out of graph state. Marking them
    PrivateStateAttr keeps them out of every subagent's input (and therefore its output), so nothing
    is ever echoed back to collide on.
    """
    assert private_state_field_names(SagaState) >= {"mode", "session_id"}


def test_mode_and_session_id_are_stripped_from_subagent_state() -> None:
    """Same regression, exercised the way deepagents' `_validate_and_prepare_state` actually
    filters state before invoking a subagent: `{k: v for k, v in state.items() if k not in
    private_state_keys}`."""
    private_state_keys = private_state_field_names(SagaState)
    state = {"messages": [], "mode": "from_scratch", "session_id": "20260811-000000-abcdef"}

    subagent_state = {k: v for k, v in state.items() if k not in private_state_keys}

    assert "mode" not in subagent_state
    assert "session_id" not in subagent_state
    assert "messages" in subagent_state
