"""Per-item word-count bands for experiment jobs.

See the design spec §1. The band comes from the corpus `word_count`, and the
rendering reuses `psalm_saga.story_length` so the directive matches what the
interactive and batch CLIs send.
"""

from __future__ import annotations

from psalm_saga.story_length import format_length_directive, parse_chapters, parse_length

DEFAULT_BAND = 0.10


def band_for_word_count(word_count: int, band: float = DEFAULT_BAND) -> str:
    """Return the `MIN-MAX` range `±band` around `word_count`, never below 1 word."""
    if word_count < 1:
        raise ValueError(f"word_count must be at least 1, got {word_count}")
    low = max(1, round(word_count * (1 - band)))
    high = max(low, round(word_count * (1 + band)))
    return f"{low}-{high}"


def directive_for(length_range: str) -> str:
    """Render the story-length directive for a `MIN-MAX` range, with chapters on auto."""
    return format_length_directive(parse_length(length_range), parse_chapters(None))
