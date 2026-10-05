"""Maps a plan's symbolic generator-family names to concrete model identifiers.

Kept separate from `psalm_saga.settings.Settings` since a plan's generator
families (e.g. "frontier", "open_weight") are a pipeline-level concept
spanning every backend, not a single `psalm_saga` agent setting.
"""

from __future__ import annotations

import os

_DEFAULT_MODELS: dict[str, str] = {
    "frontier": "anthropic:claude-sonnet-4-6",
    "open_weight": "openai:gpt-oss-120b",
}

_ENV_OVERRIDE_PREFIX = "PSALM_SAGA_EXPERIMENTS_GENERATOR_"


class UnknownGeneratorFamilyError(KeyError):
    """Raised when a job names a generator family with no configured model."""


def resolve_model(generator_family: str) -> str:
    """Resolve a plan's `generator_family` name to a concrete model identifier.

    Checks `PSALM_SAGA_EXPERIMENTS_GENERATOR_<FAMILY>` (uppercased) first,
    then the built-in defaults, so a family's model can be repointed per
    machine or run without editing code.
    """
    env_key = f"{_ENV_OVERRIDE_PREFIX}{generator_family.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    try:
        return _DEFAULT_MODELS[generator_family]
    except KeyError as exc:
        raise UnknownGeneratorFamilyError(
            f"No model configured for generator family {generator_family!r}. "
            f"Known families: {sorted(_DEFAULT_MODELS)}"
        ) from exc
