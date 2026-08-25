"""Tests for `psalm_saga.story_length` — CLI-value parsing for `--length`/
`--chapters`, directive formatting, and the shared argparse wiring both
`psalm-saga` and `psalm-saga-batch` use. No model/agent dependency.
"""

from __future__ import annotations

import argparse

import pytest

from psalm_saga.story_length import (
    ChapterSpec,
    LengthSpec,
    add_length_arguments,
    format_length_directive,
    parse_chapters,
    parse_length,
    resolve_length_arguments,
)


def test_parse_length_none_defaults_to_short_story() -> None:
    spec = parse_length(None)

    assert spec == LengthSpec("short-story", 1000, 7499, "Short Story")


def test_parse_length_category_slug() -> None:
    assert parse_length("novella") == LengthSpec("novella", 17500, 39999, "Novella")


def test_parse_length_category_is_case_insensitive() -> None:
    assert parse_length("NOVELLA") == LengthSpec("novella", 17500, 39999, "Novella")


def test_parse_length_accepts_aliases() -> None:
    assert parse_length("short").category == "short-story"
    assert parse_length("flash").category == "flash-fiction"
    assert parse_length("doorstopper").category == "epic"


def test_parse_length_drabble_is_exact() -> None:
    assert parse_length("drabble") == LengthSpec("drabble", 100, 100, "Drabble")


def test_parse_length_epic_is_open_ended() -> None:
    spec = parse_length("epic")

    assert spec.min_words == 150000
    assert spec.max_words is None


def test_parse_length_custom_exact_word_count() -> None:
    spec = parse_length("12000")

    assert spec.category is None
    assert spec.min_words == 12000
    assert spec.max_words == 12000
    assert spec.label == "custom, 12,000 words (novelette range)"


def test_parse_length_custom_hundred_words_resolves_to_drabble_bucket() -> None:
    spec = parse_length("100")

    assert spec.label == "custom, 100 words (drabble range)"


def test_parse_length_custom_range_within_one_bucket() -> None:
    spec = parse_length("8000-9000")

    assert spec.min_words == 8000
    assert spec.max_words == 9000
    assert spec.label == "custom, 8,000–9,000 words (novelette range)"


def test_parse_length_custom_range_spanning_buckets() -> None:
    spec = parse_length("12000-18000")

    assert spec.label == "custom, 12,000–18,000 words (spans novelette–novella)"


def test_parse_length_rejects_unrecognized_category() -> None:
    with pytest.raises(ValueError, match="--length must be"):
        parse_length("not-a-category")


def test_parse_length_rejects_zero() -> None:
    with pytest.raises(ValueError, match="positive"):
        parse_length("0")


def test_parse_length_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="exceeds its maximum"):
        parse_length("5000-3000")


def test_parse_chapters_none_defaults_to_auto() -> None:
    assert parse_chapters(None) == ChapterSpec(mode="auto")


def test_parse_chapters_auto_is_case_insensitive() -> None:
    assert parse_chapters("AUTO") == ChapterSpec(mode="auto")


def test_parse_chapters_exact_count() -> None:
    assert parse_chapters("6") == ChapterSpec(mode="exact", count=6)


def test_parse_chapters_range() -> None:
    assert parse_chapters("3-10") == ChapterSpec(mode="range", min_count=3, max_count=10)


def test_parse_chapters_rejects_zero() -> None:
    with pytest.raises(ValueError, match="positive"):
        parse_chapters("0")


def test_parse_chapters_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="exceeds its maximum"):
        parse_chapters("10-3")


def test_parse_chapters_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="--chapters must be"):
        parse_chapters("banana")


def test_format_length_directive_for_a_category_and_auto_chapters() -> None:
    directive = format_length_directive(parse_length("novella"), parse_chapters(None))

    assert directive == (
        "Story length directive: novella, target 17,500–39,999 words. "
        "Chapter count: auto — decide per the length-and-chapters "
        "guidance based on the resolved word target."
    )


def test_format_length_directive_for_drabble_exact_words() -> None:
    directive = format_length_directive(parse_length("drabble"), parse_chapters(None))

    assert "target exactly 100 words" in directive


def test_format_length_directive_for_epic_open_ended() -> None:
    directive = format_length_directive(parse_length("epic"), parse_chapters(None))

    assert "target 150,000+ words" in directive


def test_format_length_directive_for_custom_length_and_explicit_chapters() -> None:
    directive = format_length_directive(parse_length("12000-18000"), parse_chapters("4"))

    assert directive == (
        "Story length directive: custom, 12,000–18,000 words "
        "(spans novelette–novella). Chapter count: 4 (explicit)."
    )


def test_format_length_directive_for_chapter_range() -> None:
    directive = format_length_directive(parse_length("novel"), parse_chapters("5-8"))

    assert "Chapter count: 5–8 (explicit range)." in directive


def _build_test_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    add_length_arguments(parser)
    return parser


def test_add_length_arguments_defaults_to_none() -> None:
    args = _build_test_parser().parse_args([])

    assert args.length is None
    assert args.chapters is None


def test_resolve_length_arguments_returns_resolved_specs() -> None:
    parser = _build_test_parser()
    args = parser.parse_args(["--length", "novella", "--chapters", "5"])

    length_spec, chapter_spec = resolve_length_arguments(parser, args)

    assert length_spec.category == "novella"
    assert chapter_spec == ChapterSpec(mode="exact", count=5)


def test_resolve_length_arguments_exits_on_invalid_length() -> None:
    parser = _build_test_parser()
    args = parser.parse_args(["--length", "not-a-category"])

    with pytest.raises(SystemExit):
        resolve_length_arguments(parser, args)


def test_resolve_length_arguments_exits_on_invalid_chapters() -> None:
    parser = _build_test_parser()
    args = parser.parse_args(["--chapters", "banana"])

    with pytest.raises(SystemExit):
        resolve_length_arguments(parser, args)
