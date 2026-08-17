"""Middleware assembly for the psalm-saga agent."""

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
)
from langgraph.prebuilt.tool_node import ToolCallRequest

from psalm_saga.settings import Settings


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


def init_middleware(settings: Settings) -> Sequence[AgentMiddleware[Any, Any]]:
    """Assemble the middleware stack from settings.

    Args:
        settings: Application settings controlling which middleware is
            enabled and how each is configured.

    Returns:
        The middleware sequence to pass to `create_deep_agent(middleware=...)`.
        Note: `TodoListMiddleware` (the `write_todos` tool) and
        `SkillsMiddleware`/`FilesystemMiddleware`/`SubAgentMiddleware` are
        added separately by `create_deep_agent` itself via its own
        `skills=`/`backend=`/`subagents=` parameters — this function only
        covers the cross-cutting reliability middleware (retry, call limits,
        tool-error handling) that isn't specific to psalm-saga's skills.

    """
    middleware: list[AgentMiddleware[Any, Any]] = []

    if settings.model_retry.enable_model_retry:
        middleware.append(
            ModelRetryMiddleware(
                max_retries=settings.model_retry.max_retries,
                backoff_factor=settings.model_retry.backoff_factor,
                initial_delay=settings.model_retry.initial_delay,
                jitter=settings.model_retry.jitter,
            )
        )

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
