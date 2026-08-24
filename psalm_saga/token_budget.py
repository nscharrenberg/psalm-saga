"""Shared, token-aware backpressure for model calls sharing one provider quota.

`InMemoryRateLimiter` (used in `agent.py`) paces calls by *requests* per
second. OpenAI's per-model quota in this project is a *tokens*-per-minute
(TPM) budget shared across every caller of that model name — the
orchestrator and every dispatched subagent alike. A request-rate limiter has
no way to prevent a single large call (e.g. a chapter-writer draft) from
blowing a shared TPM budget, and if it's only attached to one of several
callers of the same model, it can't see what the others are using either.

`SlidingWindowTokenBudget` tracks token usage in a rolling window per model
name, and `get_shared_budget` hands out one instance per model name so every
caller — orchestrator and subagents — draws down the same budget regardless
of which `AgentMiddleware` stack they're attached to. `TokenBudgetMiddleware`
wraps a call: it estimates the request's token cost, blocks until there's
room in the window, executes the call, then corrects the reservation with
the actual usage reported by the model.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ContextT, ModelRequest, ModelResponse
    from langchain_core.messages import AnyMessage


class TokenBudgetTimeoutError(TimeoutError):
    """Raised when `SlidingWindowTokenBudget.reserve` can't find room in time."""


class SlidingWindowTokenBudget:
    """Tracks token usage over a rolling time window and gates new reservations.

    Not tied to any particular model client — just a thread-safe ledger of
    `(timestamp, tokens)` events, pruned to the trailing `window_seconds`.
    """

    def __init__(self, limit: int, *, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self._window_seconds = window_seconds
        self._events: deque[list[float]] = deque()
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> int:
        while self._events and now - self._events[0][0] > self._window_seconds:
            self._events.popleft()
        return int(sum(tokens for _, tokens in self._events))

    def _try_reserve(self, estimated_tokens: int) -> list[float] | None:
        with self._lock:
            now = time.monotonic()
            used = self._prune_locked(now)
            if used + estimated_tokens > self.limit and self._events:
                return None
            ticket = [now, float(estimated_tokens)]
            self._events.append(ticket)
            return ticket

    def reserve(
        self,
        estimated_tokens: int,
        *,
        poll_interval: float = 0.5,
        max_wait: float = 120.0,
    ) -> list[float]:
        """Block (sleeping) until `estimated_tokens` fits in the window, then record it.

        Returns a mutable ticket `record_actual` can later correct. Gives up
        and lets the call through anyway (returning a ticket regardless) once
        `max_wait` has elapsed — better to risk one more 429 than hang the
        agent forever on a bad estimate.
        """
        deadline = time.monotonic() + max_wait
        while True:
            ticket = self._try_reserve(estimated_tokens)
            if ticket is not None:
                return ticket
            if time.monotonic() >= deadline:
                with self._lock:
                    now = time.monotonic()
                    ticket = [now, float(estimated_tokens)]
                    self._events.append(ticket)
                    return ticket
            time.sleep(poll_interval)

    async def areserve(
        self,
        estimated_tokens: int,
        *,
        poll_interval: float = 0.5,
        max_wait: float = 120.0,
    ) -> list[float]:
        """Async counterpart of `reserve`, sleeping via `asyncio.sleep`."""
        import asyncio  # noqa: PLC0415

        deadline = time.monotonic() + max_wait
        while True:
            ticket = self._try_reserve(estimated_tokens)
            if ticket is not None:
                return ticket
            if time.monotonic() >= deadline:
                with self._lock:
                    now = time.monotonic()
                    ticket = [now, float(estimated_tokens)]
                    self._events.append(ticket)
                    return ticket
            await asyncio.sleep(poll_interval)

    def record_actual(self, ticket: list[float], actual_tokens: int) -> None:
        """Correct a reservation with the real usage once the call has returned."""
        with self._lock:
            ticket[1] = float(actual_tokens)


_budgets: dict[str, SlidingWindowTokenBudget] = {}
_budgets_lock = threading.Lock()


def get_shared_budget(model_name: str, tokens_per_minute: int) -> SlidingWindowTokenBudget:
    """Return the process-wide budget for `model_name`, creating it on first use.

    Every caller of the same model name (orchestrator, chapter-writer,
    dimension-reviewer, ...) gets the same instance here, so their usage is
    tracked against one shared window rather than each thinking it has the
    full budget to itself.
    """
    with _budgets_lock:
        budget = _budgets.get(model_name)
        if budget is None:
            budget = SlidingWindowTokenBudget(tokens_per_minute)
            _budgets[model_name] = budget
        return budget


def reset_shared_budgets() -> None:
    """Clear all shared budgets. Test-only: production code never needs this."""
    with _budgets_lock:
        _budgets.clear()


def _message_char_len(message: AnyMessage) -> int:
    content = message.content
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, str):
                total += len(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
                if isinstance(text, str):
                    total += len(text)
        return total
    return 0


def _extract_total_tokens(response: ModelResponse[Any]) -> int | None:
    for message in response.result:
        usage = getattr(message, "usage_metadata", None)
        if usage and usage.get("total_tokens"):
            return int(usage["total_tokens"])
    return None


class TokenBudgetMiddleware(AgentMiddleware["Any", "ContextT", "Any"]):
    """Blocks a model call until it fits the shared tokens-per-minute budget.

    Estimates the call's token cost from message length before making it
    (there's no way to know the real cost upfront), reserves that many
    tokens in the shared window, then corrects the reservation with the
    actual `usage_metadata` once the response comes back.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        model_name: str,
        tokens_per_minute: int,
        safety_margin: float = 0.85,
        chars_per_token_estimate: float = 4.0,
        reserved_output_tokens: int = 4096,
        poll_interval: float = 0.5,
        max_wait: float = 120.0,
    ) -> None:
        super().__init__()
        self.tools = []
        effective_limit = max(1, int(tokens_per_minute * safety_margin))
        self._budget = get_shared_budget(model_name, effective_limit)
        self._chars_per_token_estimate = max(chars_per_token_estimate, 0.1)
        self._reserved_output_tokens = reserved_output_tokens
        self._poll_interval = poll_interval
        self._max_wait = max_wait

    def _estimate_tokens(self, request: ModelRequest[Any]) -> int:
        total_chars = 0
        if request.system_message is not None:
            total_chars += _message_char_len(request.system_message)
        total_chars += sum(_message_char_len(m) for m in request.messages)
        return int(total_chars / self._chars_per_token_estimate) + self._reserved_output_tokens

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        estimated = self._estimate_tokens(request)
        ticket = self._budget.reserve(
            estimated, poll_interval=self._poll_interval, max_wait=self._max_wait
        )
        response = handler(request)
        actual = _extract_total_tokens(response)
        if actual is not None:
            self._budget.record_actual(ticket, actual)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        estimated = self._estimate_tokens(request)
        ticket = await self._budget.areserve(
            estimated, poll_interval=self._poll_interval, max_wait=self._max_wait
        )
        response = await handler(request)
        actual = _extract_total_tokens(response)
        if actual is not None:
            self._budget.record_actual(ticket, actual)
        return response
