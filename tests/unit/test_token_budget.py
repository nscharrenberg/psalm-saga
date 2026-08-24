"""Tests for `psalm_saga.token_budget`.

The bug this guards against: `InMemoryRateLimiter` paces *requests* per
second and has no concept of tokens, so a single large call can blow a
shared tokens-per-minute (TPM) budget outright — and worse, the
orchestrator and its subagents each get *separate* rate limiter instances,
so neither can see what the other is using even for request pacing. This
suite pins down that `SlidingWindowTokenBudget` actually blocks a
reservation that would exceed its window, that `get_shared_budget` really
is shared across independently-constructed callers of the same model name,
and that `TokenBudgetMiddleware` corrects its estimate with real usage.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from psalm_saga import token_budget as tb


@pytest.fixture(autouse=True)
def _clean_shared_budgets() -> None:
    tb.reset_shared_budgets()
    yield
    tb.reset_shared_budgets()


def test_reserve_allows_calls_within_the_limit() -> None:
    budget = tb.SlidingWindowTokenBudget(limit=1000)

    ticket1 = budget.reserve(400, max_wait=1.0)
    ticket2 = budget.reserve(400, max_wait=1.0)

    assert ticket1 is not None
    assert ticket2 is not None


def test_reserve_blocks_until_a_prior_reservation_ages_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call that would exceed the window must wait, not sail through."""
    budget = tb.SlidingWindowTokenBudget(limit=100, window_seconds=60.0)
    budget.reserve(90, max_wait=1.0)  # nearly fills the budget

    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    # Re-anchor the existing reservation's timestamp to the fake clock's origin.
    budget._events[0][0] = fake_now[0]  # noqa: SLF001

    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        fake_now[0] += 61.0  # jump past the window so the old reservation ages out

    monkeypatch.setattr(time, "sleep", fake_sleep)

    ticket = budget.reserve(50, poll_interval=0.5, max_wait=120.0)

    assert slept, "reserve() should have had to wait for the prior reservation to age out"
    assert ticket is not None


def test_reserve_gives_up_after_max_wait_rather_than_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = tb.SlidingWindowTokenBudget(limit=100, window_seconds=60.0)
    budget.reserve(100, max_wait=1.0)  # fills the budget completely, never ages out below

    real_monotonic = time.monotonic
    fake_now = [real_monotonic()]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    monkeypatch.setattr(time, "sleep", lambda _seconds: fake_now.__setitem__(0, fake_now[0] + 1))

    started = fake_now[0]
    ticket = budget.reserve(50, poll_interval=0.1, max_wait=2.0)

    assert ticket is not None  # gives up and lets it through rather than raising/hanging
    assert fake_now[0] - started >= 2.0


def test_get_shared_budget_returns_the_same_instance_for_the_same_model_name() -> None:
    first = tb.get_shared_budget("openai:gpt-5.6-luna", 200_000)
    second = tb.get_shared_budget("openai:gpt-5.6-luna", 200_000)

    assert first is second


def test_get_shared_budget_is_isolated_per_model_name() -> None:
    a = tb.get_shared_budget("openai:gpt-5.6-luna", 200_000)
    b = tb.get_shared_budget("openai:some-other-model", 50_000)

    assert a is not b


def test_orchestrator_and_subagent_middleware_share_one_budget_when_same_model() -> None:
    """Mirrors agent.py: two independently-constructed middleware instances
    (one for the orchestrator, one for a subagent) must draw down the same
    window when they're built for the same model name.
    """
    orchestrator_mw = tb.TokenBudgetMiddleware(
        model_name="openai:gpt-5.6-luna", tokens_per_minute=1000, safety_margin=1.0
    )
    subagent_mw = tb.TokenBudgetMiddleware(
        model_name="openai:gpt-5.6-luna", tokens_per_minute=1000, safety_margin=1.0
    )

    assert orchestrator_mw._budget is subagent_mw._budget  # noqa: SLF001


class _FakeModelRequest:
    def __init__(self, *, system_message: Any = None, messages: list[Any] | None = None) -> None:
        self.system_message = system_message
        self.messages = messages or []


def test_wrap_model_call_records_actual_usage_correcting_the_estimate() -> None:
    middleware = tb.TokenBudgetMiddleware(
        model_name="test-correction-model",
        tokens_per_minute=1_000_000,
        reserved_output_tokens=0,
        chars_per_token_estimate=4.0,
    )
    request = _FakeModelRequest(messages=[AIMessage(content="x" * 40)])  # estimate: 40/4 = 10

    def handler(_request: Any) -> Any:
        response = AIMessage(content="reply")
        response.usage_metadata = {
            "input_tokens": 500,
            "output_tokens": 20,
            "total_tokens": 520,
        }

        class _Response:
            def __init__(self) -> None:
                self.result = [response]

        return _Response()

    middleware.wrap_model_call(request, handler)

    used = middleware._budget._prune_locked(time.monotonic())  # noqa: SLF001
    assert used == 520  # corrected to actual usage, not the ~10-token estimate
