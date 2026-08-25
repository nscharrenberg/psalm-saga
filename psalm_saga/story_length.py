"""Story length and chapter-count parsing shared by both CLI entry points
(`psalm-saga` and `psalm-saga-batch`).

Length and chapter count are still creative decisions made inside
`story-brainstorming` and `writing-story-plans` — this module only turns a
`--length`/`--chapters` CLI value into a resolved target and formats the
one-line directive threaded into the agent (as extra `system_prompt` text
for a fresh interactive session, or appended to each per-story instruction
message in batch mode). The chapter-count heuristic for "auto" mode lives
in `skills/story-brainstorming/references/length-and-chapters.md`, not
here — this module never hardcodes a chapter-count formula.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

DEFAULT_LENGTH_CATEGORY = "short-story"

_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_INT_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class LengthCategory:
    """One predefined `--length` category and its word-count bounds.

    `max_words=None` means open-ended (only `epic` uses this). Every
    category is contiguous and non-overlapping starting at 1 word, except
    `drabble`, which is a single exact value nested inside
    `flash-fiction`'s wider range by design — `LENGTH_CATEGORIES` lists it
    first so an exact 100-word target resolves to `drabble`, not the
    broader `flash-fiction` bucket it also technically falls within.
    """

    slug: str
    label: str
    min_words: int
    max_words: int | None


LENGTH_CATEGORIES: tuple[LengthCategory, ...] = (
    LengthCategory("drabble", "Drabble", 100, 100),
    LengthCategory("flash-fiction", "Flash Fiction", 1, 999),
    LengthCategory("short-story", "Short Story", 1000, 7499),
    LengthCategory("novelette", "Novelette", 7500, 17499),
    LengthCategory("novella", "Novella", 17500, 39999),
    LengthCategory("novel", "Novel", 40000, 149999),
    LengthCategory("epic", "Epic / Doorstopper", 150000, None),
)

_CATEGORY_BY_SLUG: dict[str, LengthCategory] = {c.slug: c for c in LENGTH_CATEGORIES}
_CATEGORY_ALIASES: dict[str, str] = {
    "flash": "flash-fiction",
    "short": "short-story",
    "doorstopper": "epic",
}


@dataclass(frozen=True)
class LengthSpec:
    """A resolved `--length` target: either a named category, or a custom
    word count/range with `category=None`.
    """

    category: str | None
    min_words: int
    max_words: int | None
    label: str


@dataclass(frozen=True)
class ChapterSpec:
    """A resolved `--chapters` target.

    `mode="auto"` leaves the actual count to `writing-story-plans`' own
    length-and-chapters heuristic; `count`/`min_count`/`max_count` are only
    set for `mode="exact"` / `mode="range"` respectively.
    """

    mode: str
    count: int | None = None
    min_count: int | None = None
    max_count: int | None = None


def _bucket_for(word_count: int) -> LengthCategory:
    """The predefined category a raw word count falls into.

    Used only to annotate a custom `--length` value/range with a
    human-readable hint (e.g. "novelette range") — it never restricts
    what the user can type.
    """
    for category in LENGTH_CATEGORIES:
        if category.max_words is None:
            if word_count >= category.min_words:
                return category
        elif category.min_words <= word_count <= category.max_words:
            return category
    raise AssertionError(f"no length category covers {word_count} words")  # pragma: no cover


def _custom_label(min_words: int, max_words: int) -> str:
    low, high = _bucket_for(min_words), _bucket_for(max_words)
    bucket_note = (
        f"{low.label.lower()} range"
        if low is high
        else f"spans {low.label.lower()}–{high.label.lower()}"
    )
    words = f"{min_words:,}" if min_words == max_words else f"{min_words:,}–{max_words:,}"
    return f"custom, {words} words ({bucket_note})"


def parse_length(raw: str | None) -> LengthSpec:
    """Parse a `--length` CLI value.

    Accepts, case-insensitively: a category slug or alias (`novella`,
    `short`, `doorstopper`), a bare positive integer for an exact custom
    word target (`12000`), or a `MIN-MAX` custom range (`12000-18000`).
    `raw=None` (the flag omitted) resolves to `DEFAULT_LENGTH_CATEGORY`.

    Raises `ValueError` on an unrecognized category, a non-positive
    integer, or a range where `MIN > MAX`.
    """
    if raw is None:
        category = _CATEGORY_BY_SLUG[DEFAULT_LENGTH_CATEGORY]
        return LengthSpec(category.slug, category.min_words, category.max_words, category.label)

    text = raw.strip()
    slug = _CATEGORY_ALIASES.get(text.lower(), text.lower())
    if slug in _CATEGORY_BY_SLUG:
        category = _CATEGORY_BY_SLUG[slug]
        return LengthSpec(category.slug, category.min_words, category.max_words, category.label)

    range_match = _RANGE_RE.match(text)
    if range_match:
        min_words, max_words = int(range_match.group(1)), int(range_match.group(2))
        if min_words < 1:
            raise ValueError(f"--length range must start at 1 or more words, got {raw!r}")
        if min_words > max_words:
            raise ValueError(f"--length range minimum exceeds its maximum, got {raw!r}")
        return LengthSpec(None, min_words, max_words, _custom_label(min_words, max_words))

    if _INT_RE.match(text):
        words = int(text)
        if words < 1:
            raise ValueError(f"--length must be a positive word count, got {raw!r}")
        return LengthSpec(None, words, words, _custom_label(words, words))

    valid = ", ".join(c.slug for c in LENGTH_CATEGORIES)
    raise ValueError(
        f"--length must be a category ({valid}), a whole number of words, "
        f"or a MIN-MAX word range, got {raw!r}"
    )


def parse_chapters(raw: str | None) -> ChapterSpec:
    """Parse a `--chapters` CLI value.

    `raw=None` or the literal `"auto"` (case-insensitive) resolves to
    auto mode. A bare positive integer (`6`) locks an exact count; a
    `MIN-MAX` range (`3-10`) locks a range.

    Raises `ValueError` on a non-positive integer or a range where
    `MIN > MAX`.
    """
    if raw is None or raw.strip().lower() == "auto":
        return ChapterSpec(mode="auto")

    text = raw.strip()

    range_match = _RANGE_RE.match(text)
    if range_match:
        min_count, max_count = int(range_match.group(1)), int(range_match.group(2))
        if min_count < 1:
            raise ValueError(f"--chapters range must start at 1 or more, got {raw!r}")
        if min_count > max_count:
            raise ValueError(f"--chapters range minimum exceeds its maximum, got {raw!r}")
        return ChapterSpec(mode="range", min_count=min_count, max_count=max_count)

    if _INT_RE.match(text):
        count = int(text)
        if count < 1:
            raise ValueError(f"--chapters must be a positive integer, got {raw!r}")
        return ChapterSpec(mode="exact", count=count)

    raise ValueError(
        f"--chapters must be 'auto', a positive integer, or a MIN-MAX range, got {raw!r}"
    )


def format_length_directive(length: LengthSpec, chapters: ChapterSpec) -> str:
    """Build the one-line instruction threaded into the agent.

    Injected as extra `system_prompt` text for a fresh interactive
    session, or appended to each per-story instruction message in batch
    mode. `story-brainstorming` and `writing-story-plans` treat this line
    as a locked directive, the same way a template-locked dimension is
    treated.
    """
    if length.category is not None:
        category = _CATEGORY_BY_SLUG[length.category]
        if category.max_words is None:
            words_desc = f"{category.min_words:,}+ words"
        elif category.min_words == category.max_words:
            words_desc = f"exactly {category.min_words:,} words"
        else:
            words_desc = f"{category.min_words:,}–{category.max_words:,} words"
        length_desc = f"{category.label.lower()}, target {words_desc}"
    else:
        length_desc = length.label

    if chapters.mode == "auto":
        chapters_desc = (
            "auto — decide per the length-and-chapters guidance based on "
            "the resolved word target"
        )
    elif chapters.mode == "exact":
        chapters_desc = f"{chapters.count} (explicit)"
    else:
        chapters_desc = f"{chapters.min_count}–{chapters.max_count} (explicit range)"

    return f"Story length directive: {length_desc}. Chapter count: {chapters_desc}."


def add_length_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `--length` and `--chapters` to `parser`.

    Shared between `psalm-saga` and `psalm-saga-batch` so the flags, their
    help text, and their validation behave identically on both CLIs.
    """
    parser.add_argument(
        "--length",
        default=None,
        help=(
            "Target story length: a category "
            f"({', '.join(c.slug for c in LENGTH_CATEGORIES)}), an alias "
            f"({', '.join(sorted(_CATEGORY_ALIASES))}), an exact word count "
            "(e.g. 12000), or a MIN-MAX word range (e.g. 12000-18000). "
            f"Defaults to {DEFAULT_LENGTH_CATEGORY}."
        ),
    )
    parser.add_argument(
        "--chapters",
        default=None,
        help=(
            "Target chapter count: 'auto' (default; estimated from the "
            "resolved length), an exact count (e.g. 6), or a MIN-MAX range "
            "(e.g. 3-10)."
        ),
    )


def resolve_length_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[LengthSpec, ChapterSpec]:
    """Parse `args.length`/`args.chapters` (as set by `add_length_arguments`)
    into resolved specs, calling `parser.error(...)` (prints a usage
    message and exits) on an invalid value — the same failure mode as any
    other CLI argument error.
    """
    try:
        length_spec = parse_length(args.length)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        chapter_spec = parse_chapters(args.chapters)
    except ValueError as exc:
        parser.error(str(exc))
    return length_spec, chapter_spec
