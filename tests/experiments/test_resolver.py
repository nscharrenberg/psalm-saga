"""Tests for `experiments.pipeline.resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiments.pipeline.models import GenerationJob
from experiments.pipeline.resolver import InputNotFoundError, InputResolver


def _job(task: str, item_id: str = "satire_the_happy_prince", language: str = "english") -> GenerationJob:
    return GenerationJob(
        plan_name="pilot",
        task=task,  # type: ignore[arg-type]
        condition="C1",
        item_id=item_id,
        generator_family="frontier",
        language=language,
    )


def test_resolve_reads_premise_for_task_a(tmp_path: Path) -> None:
    premises = tmp_path / "premises"
    premises.mkdir()
    (premises / "satire_the_happy_prince.md").write_text("A statue learns to give.", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("A"))

    assert resolved.kind == "premise"
    assert resolved.content == "A statue learns to give."


def test_resolve_reads_gold_spec_for_task_b(tmp_path: Path) -> None:
    gold = tmp_path / "specs" / "gold"
    gold.mkdir(parents=True)
    (gold / "satire_the_happy_prince.md").write_text("# Gold spec", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("B"))

    assert resolved.kind == "gold_spec"
    assert resolved.content == "# Gold spec"


def test_resolve_reads_scratch_spec_for_task_d(tmp_path: Path) -> None:
    scratch = tmp_path / "specs" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "scratch_en_01.md").write_text("# Scratch spec", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("D", item_id="scratch_en_01"))

    assert resolved.kind == "scratch_spec"
    assert resolved.content == "# Scratch spec"


def test_resolve_reads_source_text_for_task_c(tmp_path: Path) -> None:
    stories = tmp_path / "stories" / "english"
    stories.mkdir(parents=True)
    (stories / "satire_the_happy_prince.txt").write_text("Once upon a time.", encoding="utf-8")

    resolved = InputResolver(tmp_path).resolve(_job("C"))

    assert resolved.kind == "source_text"
    assert resolved.content == "Once upon a time."


def test_resolve_raises_input_not_found_with_the_expected_path(tmp_path: Path) -> None:
    with pytest.raises(InputNotFoundError, match="satire_the_happy_prince"):
        InputResolver(tmp_path).resolve(_job("A"))
