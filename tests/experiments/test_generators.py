"""Tests for `experiments.pipeline.generators`."""

from __future__ import annotations

import pytest

from experiments.pipeline.generators import UnknownGeneratorFamilyError, resolve_model


def test_resolve_model_returns_the_default_for_a_known_family() -> None:
    assert resolve_model("frontier") == "anthropic:claude-sonnet-4-6"


def test_resolve_model_raises_for_an_unknown_family() -> None:
    with pytest.raises(UnknownGeneratorFamilyError, match="unknown_family"):
        resolve_model("unknown_family")


def test_resolve_model_honors_an_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PSALM_SAGA_EXPERIMENTS_GENERATOR_FRONTIER", "anthropic:claude-opus-5")

    assert resolve_model("frontier") == "anthropic:claude-opus-5"
