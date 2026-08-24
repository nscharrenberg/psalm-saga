"""Tests for the rate-limiter/middleware wiring in `psalm_saga.agent`.

The bug this guards against: `build_subagent_model` used to omit
`rate_limiter=` entirely (unlike `build_model`), so `settings.rate_limiter`
never applied to `chapter-writer`/`dimension-reviewer` — the callers that
actually draft the token-heavy prose. Separately, `resolved_subagents` never
set a `"middleware"` key, so `init_middleware`'s retry/token-budget stack
never reached those subagents either (deepagents does not propagate the
top-level `middleware=` list to dispatched subagents; each `SubAgent` spec
needs its own). These tests pin both down without touching real model
providers or building a full graph.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.rate_limiters import InMemoryRateLimiter

from psalm_saga import agent as agent_module
from psalm_saga.retry_middleware import RateLimitAwareRetryMiddleware
from psalm_saga.settings import Settings
from psalm_saga.token_budget import TokenBudgetMiddleware


def test_build_subagent_model_receives_a_rate_limiter_like_build_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_init_chat_model(*, model: str, rate_limiter: Any = None, **kwargs: Any) -> str:
        calls.append({"model": model, "rate_limiter": rate_limiter, **kwargs})
        return f"stub-model:{model}"

    monkeypatch.setattr(agent_module, "init_chat_model", fake_init_chat_model)

    settings = Settings()
    agent_module.build_model(settings)
    agent_module.build_subagent_model(settings)

    assert len(calls) == 2
    orchestrator_call, subagent_call = calls
    assert isinstance(orchestrator_call["rate_limiter"], InMemoryRateLimiter)
    assert isinstance(subagent_call["rate_limiter"], InMemoryRateLimiter)


def test_build_subagent_model_respects_rate_limiter_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent_module,
        "init_chat_model",
        lambda *, model, rate_limiter=None, **_kw: calls.append(
            {"model": model, "rate_limiter": rate_limiter}
        ),
    )

    settings = Settings()
    settings.rate_limiter.enable_rate_limiter = False
    agent_module.build_subagent_model(settings)

    assert calls[0]["rate_limiter"] is None


def test_build_agent_attaches_subagent_middleware_to_chapter_writer_and_dimension_reviewer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(agent_module, "init_chat_model", lambda *, model, **_kw: f"stub:{model}")

    captured: dict[str, Any] = {}

    def fake_create_deep_agent(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "stub-compiled-graph"

    monkeypatch.setattr(agent_module, "create_deep_agent", fake_create_deep_agent)

    settings = Settings()
    settings.backend.root_dir = tmp_path
    agent_module.build_agent(settings)

    resolved_subagents = captured["subagents"]
    by_name = {spec["name"]: spec for spec in resolved_subagents}

    for name in ("chapter-writer", "dimension-reviewer"):
        subagent_middleware = by_name[name]["middleware"]
        kinds = {type(m) for m in subagent_middleware}
        assert RateLimitAwareRetryMiddleware in kinds, f"{name} missing retry-after-aware retry"
        assert TokenBudgetMiddleware in kinds, f"{name} missing shared token budget"


def test_build_agent_forwards_bootstrap_skill_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(agent_module, "init_chat_model", lambda *, model, **_kw: f"stub:{model}")
    monkeypatch.setattr(agent_module, "create_deep_agent", lambda **_kwargs: "stub-compiled-graph")

    captured: dict[str, Any] = {}

    def fake_compose_system_prompt(*, application_prompt: str, bootstrap_skill: str) -> str:  # noqa: ARG001
        captured["bootstrap_skill"] = bootstrap_skill
        return "stub-system-prompt"

    monkeypatch.setattr(agent_module, "compose_system_prompt", fake_compose_system_prompt)

    settings = Settings()
    settings.backend.root_dir = tmp_path
    agent_module.build_agent(settings, bootstrap_skill="batch-story-generation")

    assert captured["bootstrap_skill"] == "batch-story-generation"
