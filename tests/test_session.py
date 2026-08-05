from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.config import Settings  # type: ignore[import-untyped]
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    StoryBible,
)
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
    assert config.non_interactive is False


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


def test_init_session_seeds_divergence_plan(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("Once upon a time...")
    plan = DivergencePlan.isolate("characters")

    session_dir = init_session(
        settings,
        GenerationMode.FROM_SOURCE,
        source_path=source,
        divergence_plan=plan,
        non_interactive=True,
    )

    bible = StoryBible.model_validate_json((session_dir / "story_bible.json").read_text())
    assert bible.divergence_plan is not None
    assert bible.divergence_plan.per_dimension["characters"] is DivergenceIntensity.CLOSE

    config = load_session_config(session_dir)
    assert config.non_interactive is True


def test_init_session_rejects_incomplete_divergence_plan(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("Once upon a time...")
    incomplete_plan = DivergencePlan(per_dimension={"characters": DivergenceIntensity.CLOSE})

    with pytest.raises(ValueError):
        init_session(
            settings, GenerationMode.FROM_SOURCE, source_path=source, divergence_plan=incomplete_plan
        )


def test_init_session_rejects_divergence_plan_in_from_scratch_mode(settings: Settings) -> None:
    plan = DivergencePlan.uniform(DivergenceIntensity.MODERATE)
    with pytest.raises(ValueError):
        init_session(settings, GenerationMode.FROM_SCRATCH, divergence_plan=plan)


def test_init_session_defaults_length_tier_to_long(settings: Settings) -> None:
    session_dir = init_session(settings, GenerationMode.FROM_SCRATCH)

    bible = StoryBible.model_validate_json((session_dir / "story_bible.json").read_text())
    assert bible.length_tier is LengthTier.LONG

    config = load_session_config(session_dir)
    assert config.length_tier == "long"


def test_init_session_honors_explicit_length_tier(settings: Settings) -> None:
    session_dir = init_session(
        settings,
        GenerationMode.FROM_SCRATCH,
        length_tier=LengthTier.MEDIUM,
        session_id="medium-session",
    )

    bible = StoryBible.model_validate_json((session_dir / "story_bible.json").read_text())
    assert bible.length_tier is LengthTier.MEDIUM

    config = load_session_config(session_dir)
    assert config.length_tier == "medium"

