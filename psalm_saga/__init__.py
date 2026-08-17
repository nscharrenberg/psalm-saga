"""PSALM SAGA Init."""

from .agent import (
    CHAPTER_WRITER_SUBAGENT,
    DIMENSION_REVIEWER_SUBAGENT,
    SKILLS_MOUNT,
    build_agent,
    build_backend,
    build_model,
)
from .bootstrap import SKILLS_DIR, build_bootstrap, compose_system_prompt
from .settings import Settings

__all__ = [
    "CHAPTER_WRITER_SUBAGENT",
    "DIMENSION_REVIEWER_SUBAGENT",
    "SKILLS_DIR",
    "SKILLS_MOUNT",
    "Settings",
    "build_agent",
    "build_backend",
    "build_bootstrap",
    "build_model",
    "compose_system_prompt",
]

__version__ = "0.1.0"
