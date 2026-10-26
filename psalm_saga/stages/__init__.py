"""Importing this package registers every built-in stage implementation."""

from psalm_saga.stages import (  # noqa: F401
    assemble,
    baselines,
    conform,
    draft,
    evaluate,
    extract,
    guard,
    plan,
    recover,
    review,
    spec,
    transform,
)
from psalm_saga.stages.base import RunContext, Stage, available, get_stage, register

__all__ = ["RunContext", "Stage", "available", "get_stage", "register"]
