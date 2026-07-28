from pathlib import Path

import pytest

from psalm_saga.config import Settings  # type: ignore[import-untyped]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path / "sessions")