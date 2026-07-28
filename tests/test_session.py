import json
from pathlib import Path

import pytest

from psalm_saga.config import Settings  # type: ignore[import-untyped]
from psalm_saga.dimensions import GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.session import init_session, load_session_config  # type: ignore[import-untyped]


def test_init_session_from_scratch_seeds_expected_files(settings: Settings) -> None:
    session_dir = init_session(settings, GenerationMode.FROM_SCRATCH, initial_context="a heist on the moon")

    assert (session_dir / "story_bible.json").exists()
    assert (session_dir / "psalm_dimensions_reference.md").exists()
    assert (session_dir / "session_config.json").exists()
    assert not (session_dir / "source.txt").exists()

    bible = StoryBible.model_validate_json((session_dir / "story_bible.json").read_text())
    assert bible.mode is GenerationMode.FROM_SCRATCH

    config = load_session_config(session_dir)
    assert config.mode is GenerationMode.FROM_SCRATCH
    assert config.initial_context == "a heist on the moon"


def test_init_session_from_source_copies_source_text(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("Once upon a time, in a kingdom of glass...")

    session_dir = init_session(settings, GenerationMode.FROM_SOURCE, source_path=source)

    copied = session_dir / "source.txt"
    assert copied.exists()
    assert copied.read_text() == source.read_text()

    bible = StoryBible.model_validate_json((session_dir / "story_bible.json").read_text())
    assert bible.source_excerpt_path == "source.txt"


def test_init_session_from_source_requires_source_path(settings: Settings) -> None:
    with pytest.raises(ValueError):
        init_session(settings, GenerationMode.FROM_SOURCE)


def test_init_session_rejects_duplicate_session_id(settings: Settings) -> None:
    init_session(settings, GenerationMode.FROM_SCRATCH, session_id="my-session")
    with pytest.raises(FileExistsError):
        init_session(settings, GenerationMode.FROM_SCRATCH, session_id="my-session")
