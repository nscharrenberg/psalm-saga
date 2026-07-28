from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class GuardStrictness(StrEnum):
    """What the originality guard does when it cannot resolve a concern within budget."""

    WARN = "warn"
    """Finalize the story anyway; 
    concerns are written into originality_findings and surfaced to the user prominently, but generation is not blocked."""

    BLOCK = "block"
    """Refuse to hand off to the writer subagent until concerns are resolved or a human explicitly overrides via the CLI."""

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PSALM_SAGA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = Field(
        description="provider:model string for init_chat_model, e.g. 'anthropic:claude-opus-4-8'."
    )
    subagent_model: str | None = Field(
        default=None,
        description="Optional override model for subagents. Defaults to `model` if unset.",
    )

    sessions_root: Path = Field(default=Path("./psalm-saga-sessions"))

    originality_guard_strictness: GuardStrictness = GuardStrictness.WARN
    originality_guard_max_revisions: int = Field(
        default=3, ge=0, description="Max revise/re-check loops before giving up per strictness."
    )

    max_brainstorm_turns: int = Field(
        default=40, description="Safety cap on ask_human round-trips per bible-filling session."
    )

    recursion_limit: int = Field(
        default=200, description="LangGraph recursion_limit passed through to graph.invoke."
    )

    def resolved_subagent_model(self) -> str:
        return self.subagent_model or self.model