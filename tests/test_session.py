from __future__ import annotations

import json
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
from psalm_saga.session import (  # type: ignore[import-untyped]
    SESSION_CONFIG_FILENAME,
    init_session,
    load_session_config,
)


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


def test_load_session_config_defaults_length_tier_for_pre_migration_sessions(
    settings: Settings, tmp_path: Path
) -> None:
    """A session_config.json written before length_tier existed has no such key. SessionConfig
    must still construct (length_tier defaulting to "long") so `saga resume` doesn't crash with
    a TypeError on old sessions."""
    session_dir = tmp_path / "pre-migration-session"
    session_dir.mkdir()

    pre_migration_config = {
        "session_id": "pre-migration-session",
        "mode": GenerationMode.FROM_SCRATCH.value,
        "created_at": "2025-01-01T00:00:00+00:00",
        "model": "claude-sonnet-4-5",
        "subagent_model": "claude-sonnet-4-5",
        "originality_guard_strictness": "moderate",
        "originality_guard_max_revisions": 3,
        "initial_context": "",
        "non_interactive": False,
    }
    (session_dir / SESSION_CONFIG_FILENAME).write_text(
        json.dumps(pre_migration_config, indent=2), encoding="utf-8"
    )

    config = load_session_config(session_dir)

    assert config.length_tier == "long"

