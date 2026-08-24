"""Tests for `psalm_saga.bootstrap`'s `bootstrap_skill` override — the
mechanism `psalm-saga-batch` uses to force-inject `batch-story-generation`
instead of `using-psalm-saga` for a batch session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.bootstrap import (
    BATCH_BOOTSTRAP_SKILL,
    BOOTSTRAP_SKILL,
    build_batch_bootstrap,
    build_bootstrap,
    compose_batch_system_prompt,
    compose_system_prompt,
)


def _write_skill(skills_dir: Path, name: str, body: str) -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n\n{body}\n")


def test_build_bootstrap_defaults_to_using_psalm_saga(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = build_bootstrap(tmp_path)

    assert "Interactive body." in result
    assert "Batch body." not in result


def test_build_bootstrap_honors_bootstrap_skill_override(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = build_bootstrap(tmp_path, bootstrap_skill=BATCH_BOOTSTRAP_SKILL)

    assert "Batch body." in result
    assert "Interactive body." not in result


def test_build_batch_bootstrap_matches_explicit_override(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    assert build_batch_bootstrap(tmp_path) == build_bootstrap(
        tmp_path, bootstrap_skill=BATCH_BOOTSTRAP_SKILL
    )


def test_build_bootstrap_missing_skill_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_bootstrap(tmp_path, bootstrap_skill="does-not-exist")


def test_compose_batch_system_prompt_prepends_application_prompt(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = compose_batch_system_prompt("My app prompt.", tmp_path)

    assert result.startswith("My app prompt.")
    assert "Batch body." in result


def test_compose_system_prompt_default_behavior_unchanged(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")

    result = compose_system_prompt(skills_dir=tmp_path)

    assert "Interactive body." in result
