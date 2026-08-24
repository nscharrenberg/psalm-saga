"""Tests for `psalm_saga.batch_cli`'s argument parsing/validation and
per-story instruction building — the pieces that don't need a running
agent. See the main-loop tests further down this file for `run_batch`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.batch_cli import _build_story_instruction, _parse_args


def test_parse_args_defaults_combine_to_mixed_for_context() -> None:
    args = _parse_args(["--count", "3", "--mode", "context", "--context", "a spooky forest"])

    assert args.combine == "mixed"


def test_parse_args_forces_combine_separate_for_variant() -> None:
    args = _parse_args(
        ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "separate"]
    )

    assert args.combine == "separate"


def test_parse_args_rejects_combine_mixed_for_variant() -> None:
    with pytest.raises(SystemExit):
        _parse_args(
            ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "mixed"]
        )


def test_parse_args_rejects_count_below_one() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--count", "0", "--mode", "scratch"])


def test_parse_args_collects_repeated_context_paths() -> None:
    args = _parse_args(
        [
            "--count",
            "1",
            "--mode",
            "context",
            "--context-path",
            "a.txt",
            "--context-path",
            "b.txt",
        ]
    )

    assert args.context_paths == [Path("a.txt"), Path("b.txt")]


def test_build_story_instruction_for_scratch_mode() -> None:
    message = _build_story_instruction(1, 5, "scratch", "mixed", None, set())

    assert "story 1 of 5" in message
    assert "Mode: scratch" in message


def test_build_story_instruction_includes_existing_names() -> None:
    message = _build_story_instruction(2, 5, "context", "mixed", ["a spooky forest"], {"story-a"})

    assert "story-a" in message
