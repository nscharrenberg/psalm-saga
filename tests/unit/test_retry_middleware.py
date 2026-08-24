"""Tests for `psalm_saga.retry_middleware.RateLimitAwareRetryMiddleware`.

The bug this guards against: `langchain`'s built-in `ModelRetryMiddleware`
computes its retry delay purely from the attempt number, never looking at
the exception — so it can't honor a 429's "Please try again in 3.608s."
This suite pins down that our replacement (a) parses that hint out of a
raw-message-only exception (the shape actually seen in production — see
psalm_saga/retry_middleware.py's module docstring) and (b) actually sleeps
that long, not the exponential-backoff schedule, when the hint is present.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from psalm_saga.retry_middleware import RateLimitAwareRetryMiddleware, parse_retry_after_seconds


class _RateLimitLikeError(Exception):
    """Mirrors the production exception: only a message, no `.response`."""


@pytest.mark.parametrize(
    ("message", "expected_seconds"),
    [
        ("Rate limit reached. Please try again in 3.608s.", 3.608),
        ("Please try again in 250ms.", 0.25),
        ("Please try again in 2m.", 120.0),
        ("Please try again in 1.5 seconds.", 1.5),
        ("Nothing about waiting here.", None),
    ],
)
def test_parse_retry_after_seconds(message: str, expected_seconds: float | None) -> None:
    result = parse_retry_after_seconds(_RateLimitLikeError(message))
    if expected_seconds is None:
        assert result is None
    else:
        assert result == pytest.approx(expected_seconds)


def test_parse_retry_after_falls_back_to_response_header_when_no_message_hint() -> None:
    class _Response:
        def __init__(self) -> None:
            self.headers = {"retry-after": "7"}

    exc = _RateLimitLikeError("Some other 429 body with no explicit wait time")
    exc.response = _Response()  # type: ignore[attr-defined]

    assert parse_retry_after_seconds(exc) == pytest.approx(7.0)


class _FakeModelRequest:
    """Stand-in for `ModelRequest`; the middleware only forwards it."""


def test_wrap_model_call_honors_retry_after_over_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parseable server hint must drive the sleep, not initial_delay/backoff_factor."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    attempts = {"count": 0}

    def handler(_request: Any) -> AIMessage:
        attempts["count"] += 1
        if attempts["count"] == 1:
            msg = "Rate limit reached for gpt-5.6-luna ... Please try again in 3.608s."
            raise _RateLimitLikeError(msg)
        return AIMessage(content="ok")

    middleware = RateLimitAwareRetryMiddleware(
        max_retries=3,
        # Deliberately large exponential schedule so a pass only happens if
        # honor_retry_after actually wins, not the backoff schedule.
        initial_delay=30.0,
        backoff_factor=2.0,
        retry_after_buffer=0.5,
    )

    result = middleware.wrap_model_call(_FakeModelRequest(), handler)

    assert isinstance(result, AIMessage)
    assert result.content == "ok"
    assert attempts["count"] == 2
    assert sleeps == [pytest.approx(3.608 + 0.5)]


def test_wrap_model_call_falls_back_to_backoff_without_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)  # deterministic, no jitter noise

    attempts = {"count": 0}

    def handler(_request: Any) -> AIMessage:
        attempts["count"] += 1
        if attempts["count"] == 1:
            msg = "Some transient failure, no wait-time hint here"
            raise _RateLimitLikeError(msg)
        return AIMessage(content="ok")

    middleware = RateLimitAwareRetryMiddleware(
        max_retries=3, initial_delay=1.0, backoff_factor=2.0, jitter=True
    )

    result = middleware.wrap_model_call(_FakeModelRequest(), handler)

    assert result.content == "ok"
    assert sleeps == [pytest.approx(1.0)]  # initial_delay * backoff_factor**0


def test_wrap_model_call_gives_up_after_max_retries_with_formatted_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def handler(_request: Any) -> AIMessage:
        msg = "Please try again in 0.1s."
        raise _RateLimitLikeError(msg)

    middleware = RateLimitAwareRetryMiddleware(max_retries=2, retry_after_buffer=0.0)

    response = middleware.wrap_model_call(_FakeModelRequest(), handler)

    assert len(response.result) == 1
    content = response.result[0].content
    assert "Model call failed after 3 attempts" in content
    assert "_RateLimitLikeError" in content


def test_wrap_model_call_raises_immediately_when_on_failure_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def handler(_request: Any) -> AIMessage:
        msg = "Please try again in 0.1s."
        raise _RateLimitLikeError(msg)

    middleware = RateLimitAwareRetryMiddleware(max_retries=0, on_failure="error")

    with pytest.raises(_RateLimitLikeError):
        middleware.wrap_model_call(_FakeModelRequest(), handler)
