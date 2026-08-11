from psalm_saga.agents.orchestrator import _build_system_prompt  # type: ignore[import-untyped]
from psalm_saga.config import Settings  # type: ignore[import-untyped]


def test_system_prompt_includes_configured_max_brainstorm_turns() -> None:
    settings = Settings(model="anthropic:claude-opus-4-8", max_brainstorm_turns=55)
    prompt = _build_system_prompt(settings)
    assert "max_brainstorm_turns" in prompt
    assert "55" in prompt


def test_system_prompt_still_contains_the_base_orchestrator_prompt() -> None:
    settings = Settings(model="anthropic:claude-opus-4-8")
    prompt = _build_system_prompt(settings)
    assert "You are the orchestrator for PSALM-SAGA" in prompt
