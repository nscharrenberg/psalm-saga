"""Application settings for the psalm-saga agent.

All settings are configurable via environment variables (or a `.env` file,
loaded by the CLI) prefixed `PSALM_SAGA_`, using nested-delimiter syntax for
sub-settings, e.g. `PSALM_SAGA_AGENT__ORCHESTRATION_MODEL_NAME=anthropic:claude-sonnet-4-6`
or `PSALM_SAGA_BACKEND__ROOT_DIR=./my-story`.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PersonalSettings(BaseModel):
    """User-specific settings and preferences.

    Attributes:
        name: How the agent should address you. Defaults to "human".

    """

    name: str = Field(description="How the agent should call you", default="human")


class AgentSettings(BaseModel):
    """Settings for configuring the agent's models.

    Attributes:
        orchestration_model_name: The model driving the main agent loop —
            brainstorming dialogue, planning, and dispatch decisions.
        subagent_model_name: The model used for the `chapter-writer` and
            `dimension-reviewer` subagents when they don't override it
            themselves. Prose quality benefits from a capable model here;
            `dimension-reviewer`'s structured checklist work is usually fine
            on a faster/cheaper one — see `agent.py` for where these are
            actually wired to each named subagent.
        model_kwargs: Extra keyword arguments forwarded to
            `init_chat_model()` when building the orchestration model.
            Provider- and model-specific — most people won't need this. The
            one common case: OpenAI's GPT-5-family reasoning models (`gpt-5`,
            `gpt-5.1`-`5.x`, o-series) reject `reasoning_effort` together
            with function tools on the Chat Completions API, which deepagents
            always uses tools with, so `chat/completions` fails outright for
            these models. Fix: route through OpenAI's Responses API instead
            — set `PSALM_SAGA_AGENT__MODEL_KWARGS='{"use_responses_api": true}'`
            (JSON; pydantic-settings decodes dict-typed fields from env vars
            this way).
        subagent_model_kwargs: Same as `model_kwargs`, but for the
            `chapter-writer` / `dimension-reviewer` subagents' model. Kept
            separate since the subagent model can be a different
            provider/model than the orchestration one.

    """

    orchestration_model_name: str = Field(
        default="anthropic:claude-sonnet-4-6",
        description="The model to use for the main agent loop",
    )
    subagent_model_name: str = Field(
        default="anthropic:claude-sonnet-4-6",
        description="The model to use for chapter-writer and dimension-reviewer subagents",
    )
    model_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to init_chat_model() for the orchestration model",
    )
    subagent_model_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to init_chat_model() for the subagent model",
    )


class BackendSettings(BaseModel):
    """Settings for where the agent reads and writes story files.

    Attributes:
        root_dir: The directory specs, plans, and chapter files are read
            from and written to. Defaults to the current working directory
            the CLI was launched from, so `psalm-saga` behaves like a normal
            CLI tool operating on "the current project."
        enable_shell: Whether to give the agent a working `execute` (shell)
            tool via `LocalShellBackend`. None of the psalm-saga skills need
            shell access, so this defaults to False; the filesystem tools
            (`read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`)
            are always available regardless of this setting.

    """

    root_dir: Path = Field(
        default_factory=Path.cwd,
        description="Directory the agent reads and writes story files in",
    )
    enable_shell: bool = Field(
        default=False,
        description="Give the agent unsandboxed local shell access via LocalShellBackend",
    )


class RateLimiterSettings(BaseModel):
    """Settings for the model call rate limiter.

    Attributes:
        enable_rate_limiter: Whether to rate-limit model calls.
        requests_per_second: Maximum requests per second.
        check_every_n_seconds: How often the limiter checks for capacity.
        max_bucket_size: Maximum burst capacity.

    """

    enable_rate_limiter: bool = Field(default=True, description="Enable rate limiter")
    requests_per_second: int = Field(default=25, description="The number of requests per second")
    check_every_n_seconds: float = Field(
        default=0.1, description="The time interval to check the rate limiter"
    )
    max_bucket_size: int = Field(
        default=50, description="The maximum number of requests in the rate limiter bucket"
    )


class ModelRetrySettings(BaseModel):
    """Settings for retrying failed model calls.

    Attributes:
        enable_model_retry: Whether to retry failed model calls.
        max_retries: Maximum number of retries before giving up.
        backoff_factor: Multiplier applied to the delay between retries.
        initial_delay: Delay in seconds before the first retry.
        jitter: Whether to add randomness to retry delays.
        honor_retry_after: Whether to parse a provider-suggested wait time
            out of the error (e.g. OpenAI's "Please try again in 3.608s.")
            and sleep that instead of the exponential-backoff schedule
            below. Falls back to the backoff schedule when no such hint can
            be parsed out of the exception.
        retry_after_buffer: Extra seconds padded onto a parsed
            provider-suggested wait, since the reported time is measured at
            the moment the 429 was raised, not at the moment the retry
            actually fires.

    """

    enable_model_retry: bool = Field(default=True, description="Enable model retry")
    max_retries: int = Field(
        default=3, description="The maximum number of retries for a model call"
    )
    backoff_factor: float = Field(
        default=2.0, description="The backoff factor for retrying a model call"
    )
    initial_delay: float = Field(
        default=1.0, description="The initial delay for retrying a model call"
    )
    jitter: bool = Field(default=True, description="Enable jitter for retrying a model call")
    honor_retry_after: bool = Field(
        default=True,
        description="Parse and honor a provider-suggested wait time before falling back to backoff",
    )
    retry_after_buffer: float = Field(
        default=0.5,
        description="Extra seconds padded onto a parsed provider-suggested wait",
    )


class TokenBudgetSettings(BaseModel):
    """Settings for the shared tokens-per-minute backpressure limiter.

    Unlike `RateLimiterSettings` (which paces *requests* per second),
    this tracks actual *token* usage in a rolling 60s window, shared across
    every caller of the same model name — the orchestrator and every
    dispatched subagent alike, since they typically draw on the same
    provider quota. It blocks a model call before it's made if the call
    would likely exceed that shared budget, rather than only reacting after
    a 429 has already happened.

    Attributes:
        enable_token_budget: Whether to enforce the shared token budget.
        tokens_per_minute: The provider's TPM limit for the model these
            calls share. Set this to match your org's actual limit (see
            your provider's rate-limits page) — it's specific to your
            account tier and the model in question.
        safety_margin: Fraction of `tokens_per_minute` actually usable
            before calls block, leaving headroom for the token estimate's
            inherent inaccuracy.
        chars_per_token_estimate: Rough chars-per-token used to estimate a
            call's input size before it's made. The actual usage is
            recorded afterward and corrects the window for later calls.
        reserved_output_tokens: Assumed output+reasoning tokens reserved
            per call before the real usage is known.
        max_wait_seconds: Give up waiting for budget headroom after this
            long and let the call through anyway.
        poll_interval_seconds: How often to recheck budget headroom while
            waiting for capacity.

    """

    enable_token_budget: bool = Field(default=True, description="Enable the shared token budget")
    tokens_per_minute: int = Field(
        default=200_000, description="The provider's tokens-per-minute limit for this model"
    )
    safety_margin: float = Field(
        default=0.85, description="Fraction of tokens_per_minute usable before calls block"
    )
    chars_per_token_estimate: float = Field(
        default=4.0, description="Rough chars-per-token used to estimate a call's input size"
    )
    reserved_output_tokens: int = Field(
        default=4096, description="Assumed output+reasoning tokens reserved per call"
    )
    max_wait_seconds: float = Field(
        default=120.0, description="Give up waiting for budget headroom after this long"
    )
    poll_interval_seconds: float = Field(
        default=0.5, description="How often to recheck budget headroom while waiting"
    )


class ModelCallLimitSettings(BaseModel):
    """Settings for capping total model calls.

    Attributes:
        enable_call_limit: Whether to enforce a model call limit.
        thread_limit: Max model calls per conversation thread (None = unlimited).
        run_limit: Max model calls per single run (None = unlimited).
        exit_behavior: What to do when the limit is exceeded — `'end'` stops
            gracefully, `'error'` raises.

    """

    enable_call_limit: bool = Field(default=True, description="Enable call limit")
    thread_limit: int | None = Field(
        default=None, description="The maximum number of model calls allowed per thread"
    )
    run_limit: int | None = Field(
        default=50, description="The maximum number of model calls allowed per run"
    )
    exit_behavior: Literal["end", "error"] = Field(
        default="end", description="What to do when limits are exceeded: 'end' or 'error'"
    )


class ToolCallLimitSettings(BaseModel):
    """Settings for capping total tool calls.

    Attributes:
        enable_call_limit: Whether to enforce a tool call limit.
        thread_limit: Max tool calls per conversation thread (None = unlimited).
        run_limit: Max tool calls per single run (None = unlimited).
        exit_behavior: What to do when the limit is exceeded — `'continue'`
            blocks just the exceeded tool, `'end'` stops gracefully,
            `'error'` raises.

    """

    enable_call_limit: bool = Field(default=True, description="Enable call limit")
    thread_limit: int | None = Field(
        default=None, description="The maximum number of tool calls allowed per thread"
    )
    run_limit: int | None = Field(
        default=200, description="The maximum number of tool calls allowed per run"
    )
    exit_behavior: Literal["continue", "end", "error"] = Field(
        default="end", description="What to do when limits are exceeded"
    )


class Settings(BaseSettings):
    """Top-level application settings.

    Ties together every configuration section below. Populated from
    environment variables prefixed `PSALM_SAGA_` (see module docstring for
    the nested-delimiter syntax), with sensible defaults for everything so
    `psalm-saga` runs out of the box given only a model provider API key.

    Attributes:
        personal: How the agent should address you.
        agent: Which models drive the main loop and subagents.
        backend: Where the agent reads/writes story files, and whether it
            has shell access.
        rate_limiter: Model-call rate limiting.
        model_retry: Model-call retry behaviour.
        token_budget: Shared tokens-per-minute backpressure across the
            orchestrator and its subagents.
        model_call_limit: Caps on total model calls.
        tool_call_limit: Caps on total tool calls.

    """

    model_config = SettingsConfigDict(env_prefix="psalm_saga_", env_nested_delimiter="__")
    personal: PersonalSettings = PersonalSettings()
    agent: AgentSettings = AgentSettings()
    backend: BackendSettings = BackendSettings()
    rate_limiter: RateLimiterSettings = RateLimiterSettings()
    model_retry: ModelRetrySettings = ModelRetrySettings()
    token_budget: TokenBudgetSettings = TokenBudgetSettings()
    model_call_limit: ModelCallLimitSettings = ModelCallLimitSettings()
    tool_call_limit: ToolCallLimitSettings = ToolCallLimitSettings()
