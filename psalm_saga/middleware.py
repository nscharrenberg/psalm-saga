"""Middleware assembly for the psalm-saga agent."""

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langgraph.prebuilt.tool_node import ToolCallRequest

from psalm_saga.retry_middleware import RateLimitAwareRetryMiddleware
from psalm_saga.settings import Settings
from psalm_saga.token_budget import TokenBudgetMiddleware


def on_error(exc: Exception, request: ToolCallRequest) -> str | None:
    """Format a retryable error message for a failed tool call.

    Only `ValueError` is treated as a model-correctable mistake (bad tool
    input) worth turning into a message the model can act on; anything else
    is left to the surrounding middleware stack's own error handling.

    Args:
        exc: The exception raised during the tool call.
        request: The tool call request that failed.

    Returns:
        A message to send back to the model in place of the tool's normal
        output, or `None` to let the error propagate.

    """
    if isinstance(exc, ValueError):
        return f"Tool `{request.tool_call['name']}` failed: {type(exc).__name__}. Fix the input and retry."

    return None


def _retry_middleware(settings: Settings) -> RateLimitAwareRetryMiddleware | None:
    """Build the shared retry-after-aware retry middleware, or `None` if disabled."""
    if not settings.model_retry.enable_model_retry:
        return None
    return RateLimitAwareRetryMiddleware(
        max_retries=settings.model_retry.max_retries,
        backoff_factor=settings.model_retry.backoff_factor,
        initial_delay=settings.model_retry.initial_delay,
        jitter=settings.model_retry.jitter,
        honor_retry_after=settings.model_retry.honor_retry_after,
        retry_after_buffer=settings.model_retry.retry_after_buffer,
    )


def _token_budget_middleware(settings: Settings, model_name: str) -> TokenBudgetMiddleware | None:
    """Build the shared token-budget middleware for `model_name`, or `None` if disabled.

    Keyed by `model_name` (via `token_budget.get_shared_budget`) so the
    orchestrator and every subagent that happens to use the same model name
    draw down one shared tokens-per-minute window instead of each thinking
    it has the full budget to itself.
    """
    if not settings.token_budget.enable_token_budget:
        return None
    return TokenBudgetMiddleware(
        model_name=model_name,
        tokens_per_minute=settings.token_budget.tokens_per_minute,
        safety_margin=settings.token_budget.safety_margin,
        chars_per_token_estimate=settings.token_budget.chars_per_token_estimate,
        reserved_output_tokens=settings.token_budget.reserved_output_tokens,
        poll_interval=settings.token_budget.poll_interval_seconds,
        max_wait=settings.token_budget.max_wait_seconds,
    )


def init_middleware(settings: Settings) -> Sequence[AgentMiddleware[Any, Any]]:
    """Assemble the main agent's middleware stack from settings.

    Args:
        settings: Application settings controlling which middleware is
            enabled and how each is configured.

    Returns:
        The middleware sequence to pass to `create_deep_agent(middleware=...)`.
        Note: `TodoListMiddleware` (the `write_todos` tool) and
        `SkillsMiddleware`/`FilesystemMiddleware`/`SubAgentMiddleware` are
        added separately by `create_deep_agent` itself via its own
        `skills=`/`backend=`/`subagents=` parameters — this function only
        covers the cross-cutting reliability middleware (retry, token
        budget, call limits, tool-error handling) that isn't specific to
        psalm-saga's skills.

        Only covers the top-level/orchestrator agent — `create_deep_agent`
        does not apply this list to dispatched subagents (they get their
        own middleware stack per `SubAgent["middleware"]`); use
        `init_subagent_middleware` for those.

    """
    middleware: list[AgentMiddleware[Any, Any]] = []

    retry = _retry_middleware(settings)
    if retry is not None:
        middleware.append(retry)

    budget = _token_budget_middleware(settings, settings.agent.orchestration_model_name)
    if budget is not None:
        middleware.append(budget)

    if settings.model_call_limit.enable_call_limit:
        middleware.append(
            ModelCallLimitMiddleware(
                run_limit=settings.model_call_limit.run_limit,
                thread_limit=settings.model_call_limit.thread_limit,
                exit_behavior=settings.model_call_limit.exit_behavior,
            )
        )

    if settings.tool_call_limit.enable_call_limit:
        middleware.append(
            ToolCallLimitMiddleware(
                run_limit=settings.tool_call_limit.run_limit,
                thread_limit=settings.tool_call_limit.thread_limit,
                exit_behavior=settings.tool_call_limit.exit_behavior,
            )
        )

    middleware.append(ToolErrorMiddleware(on_error=on_error))

    return middleware


def init_subagent_middleware(settings: Settings) -> Sequence[AgentMiddleware[Any, Any]]:
    """Assemble the middleware stack for a dispatched subagent.

    `create_deep_agent` does *not* apply `init_middleware`'s list to
    subagents — each `SubAgent` spec gets its own middleware via its
    `middleware` key (see `deepagents.middleware.subagents.create_sub_agent`),
    on top of deepagents' own default stack. Without this, subagents such as
    `chapter-writer` — which make the largest, most token-hungry calls of
    any caller in this app — would run with none of the reliability
    middleware `init_middleware` sets up for the orchestrator, even though
    both draw on the same provider quota when they share a model name.

    Deliberately narrower than `init_middleware`: only the retry and
    token-budget middleware, which are what a subagent's own token-heavy
    model calls need to not blow the shared TPM budget. Call/thread limits
    and tool-error formatting stay orchestrator-only concerns.
    """
    middleware: list[AgentMiddleware[Any, Any]] = []

    retry = _retry_middleware(settings)
    if retry is not None:
        middleware.append(retry)

    budget = _token_budget_middleware(settings, settings.agent.subagent_model_name)
    if budget is not None:
        middleware.append(budget)

    return middleware
