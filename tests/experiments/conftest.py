"""Shared fixtures for the experiment harness tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_generator_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear `PSALM_SAGA_EXPERIMENTS_GENERATOR_*` before each test.

    `cli.main()` calls `load_dotenv()`, which walks up from the module and can
    pick up a developer's `.env` override. Tests must not depend on it.
    """
    prefix = "PSALM_SAGA_EXPERIMENTS_GENERATOR_"
    for key in [k for k in os.environ if k.startswith(prefix)]:
        monkeypatch.delenv(key)
