# tests/experiments/test_length.py
from __future__ import annotations

import pytest

from experiments.pipeline.length import band_for_word_count, directive_for


def test_band_is_plus_minus_ten_percent_of_the_source_word_count() -> None:
    assert band_for_word_count(300) == "270-330"


def test_band_never_goes_below_one_word() -> None:
    assert band_for_word_count(1) == "1-1"


def test_directive_names_the_word_range() -> None:
    directive = directive_for("270-330")
    assert "270" in directive and "330" in directive
