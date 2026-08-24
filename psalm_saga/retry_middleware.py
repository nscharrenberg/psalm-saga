"""Model-call retry middleware that honors a provider's suggested wait time.

`langchain.agents.middleware.ModelRetryMiddleware` retries on a fixed
exponential-backoff schedule (`initial_delay * backoff_factor ** attempt`)
computed purely from the attempt number — it never looks at the exception,
so it can't know that a 429 response already told it exactly how long to
wait (e.g. OpenAI's "Please try again in 3.608s."). `RateLimitAwareRetryMiddleware`
is a drop-in replacement: same retry-loop/backoff/on_failure behavior for
ordinary failures, but when an exception's message carries a parseable
wait-time hint, it sleeps that (plus a small buffer) instead of guessing.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import TYPE_CHECKING

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelResponse,
    ResponseT,
)
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ModelRequest

    OnFailure = str | Callable[[Exception], str]


_RETRY_AFTER_PATTERN = re.compile(
    r"try again in\s*([\d.]+)\s*(ms|milliseconds|s|sec|seconds|m|min|minutes)?",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "ms": 0.001,
    "milliseconds": 0.001,
    "s": 1.0,
    "sec": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "minutes": 60.0,
}


def parse_retry_after_seconds(exc: Exception) -> float | None:
    """Extract a provider-suggested wait time from an exception, if present.

    Checks the exception's own message text first (this is where OpenAI's
    "Please try again in 3.608s." lands, regardless of which exception
    subclass ends up being raised), then falls back to a `Retry-After`
    header if the exception carries an HTTP response object.
    """
    match = _RETRY_AFTER_PATTERN.search(str(exc))
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        return value * _UNIT_SECONDS.get(unit, 1.0)

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    header = headers.get("retry-after") if headers is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            return None

    return None


def _exponential_delay(
    attempt: int, *, backoff_factor: float, initial_delay: float, max_delay: float, jitter: bool
) -> float:
    delay = initial_delay if backoff_factor == 0.0 else initial_delay * (backoff_factor**attempt)
    delay = min(delay, max_delay)
    if jitter and delay > 0:
        spread = delay * 0.25
        delay = max(0.0, delay + random.uniform(-spread, spread))  # noqa: S311
    return delay


class RateLimitAwareRetryMiddleware(AgentMiddleware[AgentState[ResponseT], ContextT, ResponseT]):
    """`ModelRetryMiddleware`, but a parseable server-suggested wait wins over backoff."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        max_retries: int = 3,
        on_failure: OnFailure = "continue",
        backoff_factor: float = 2.0,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
        honor_retry_after: bool = True,
        retry_after_buffer: float = 0.5,
    ) -> None:
        super().__init__()
        self.tools = []
        self.max_retries = max_retries
        self.on_failure = on_failure
        self.backoff_factor = backoff_factor
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.honor_retry_after = honor_retry_after
        self.retry_after_buffer = retry_after_buffer

    def _delay_for(self, exc: Exception, attempt: int) -> float:
        if self.honor_retry_after:
            suggested = parse_retry_after_seconds(exc)
            if suggested is not None:
                return suggested + self.retry_after_buffer
        return _exponential_delay(
            attempt,
            backoff_factor=self.backoff_factor,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
        )

    @staticmethod
    def _format_failure_message(exc: Exception, attempts_made: int) -> AIMessage:
        exc_type = type(exc).__name__
        attempt_word = "attempt" if attempts_made == 1 else "attempts"
        content = f"Model call failed after {attempts_made} {attempt_word} with {exc_type}: {exc}"
        return AIMessage(content=content)

    def _handle_failure(self, exc: Exception, attempts_made: int) -> ModelResponse[ResponseT]:
        if self.on_failure == "error":
            raise exc
        if callable(self.on_failure):
            return ModelResponse(result=[AIMessage(content=self.on_failure(exc))])
        return ModelResponse(result=[self._format_failure_message(exc, attempts_made)])

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT] | AIMessage:
        for attempt in range(self.max_retries + 1):
            try:
                return handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001
                attempts_made = attempt + 1
                if attempt >= self.max_retries:
                    return self._handle_failure(exc, attempts_made)
                delay = self._delay_for(exc, attempt)
                if delay > 0:
                    time.sleep(delay)

        msg = "Unexpected: retry loop completed without returning"
        raise RuntimeError(msg)

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT] | AIMessage:
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001
                attempts_made = attempt + 1
                if attempt >= self.max_retries:
                    return self._handle_failure(exc, attempts_made)
                delay = self._delay_for(exc, attempt)
                if delay > 0:
                    await asyncio.sleep(delay)

        msg = "Unexpected: retry loop completed without returning"
        raise RuntimeError(msg)
