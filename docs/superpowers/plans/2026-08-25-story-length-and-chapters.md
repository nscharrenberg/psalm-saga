# Story Length and Chapter Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--length` and `--chapters` flag to both `psalm-saga` and `psalm-saga-batch` that resolve to a target word count/category and an explicit-or-auto chapter count, threaded into the agent as a locked directive both skills honor.

**Architecture:** A new leaf module, `psalm_saga/story_length.py`, owns the length taxonomy, CLI-value parsing/validation, argparse wiring shared by both CLIs, and directive-string formatting. `batch_cli.py` appends the formatted directive to each per-story instruction message; `cli.py` passes it as extra `system_prompt` text to `build_agent(...)`, but only for a brand-new session (never on `--session` resume). Three skill files gain small, explicitly-delimited additions: a new shared reference file documents the taxonomy and the chapter-count heuristic; `story-brainstorming` and `writing-story-plans` are taught to treat an injected directive as locked input instead of asking; `batch-story-generation` documents that the per-story message may carry one.

**Tech Stack:** Python 3.14, argparse, pytest, dataclasses (matching `psalm_saga.batch_inputs`'s existing style).

**Spec:** `docs/superpowers/specs/2026-08-25-story-length-and-chapters-design.md`

## Global Constraints

- Length categories are non-overlapping except `drabble` (exactly 100 words), which is intentionally nested inside `flash-fiction`'s wider 1–999 range — `drabble` must be checked first so an exact 100-word target resolves to it.
- Category boundaries (from the spec): `drabble` 100, `flash-fiction` 1–999, `short-story` 1,000–7,499, `novelette` 7,500–17,499, `novella` 17,500–39,999, `novel` 40,000–149,999, `epic` 150,000+.
- Default `--length` (flag omitted) is `short-story`; default `--chapters` (flag omitted, or `auto`) is auto-estimation, never a hardcoded number.
- `psalm-saga-batch`'s `--length`/`--chapters` apply uniformly to every story in one run (no per-story variation).
- `psalm-saga`'s directive is only injected into `system_prompt` for a **fresh** session; a resumed session (`--session <existing-id>`) never receives it.
- The chapter-count *heuristic* (how "auto" gets resolved) lives only in `skills/story-brainstorming/references/length-and-chapters.md` — `story_length.py` never hardcodes a chapter-count formula.
- Invalid `--length`/`--chapters` values fail CLI argument parsing via `parser.error(...)` (matching the existing `--count`/`--combine` validation pattern in `batch_cli.py`), not a raw traceback.

---

## Task 1: `story_length.py` — taxonomy, parsing, directive formatting, CLI wiring

**Files:**
- Create: `psalm_saga/story_length.py`
- Test: `tests/unit/test_story_length.py`

**Interfaces:**
- Produces (used by Tasks 2 and 3):
  - `LengthCategory` (dataclass: `slug: str`, `label: str`, `min_words: int`, `max_words: int | None`)
  - `LENGTH_CATEGORIES: tuple[LengthCategory, ...]`
  - `DEFAULT_LENGTH_CATEGORY: str` (`"short-story"`)
  - `LengthSpec` (dataclass: `category: str | None`, `min_words: int`, `max_words: int | None`, `label: str`)
  - `ChapterSpec` (dataclass: `mode: str`, `count: int | None = None`, `min_count: int | None = None`, `max_count: int | None = None`)
  - `parse_length(raw: str | None) -> LengthSpec`
  - `parse_chapters(raw: str | None) -> ChapterSpec`
  - `format_length_directive(length: LengthSpec, chapters: ChapterSpec) -> str`
  - `add_length_arguments(parser: argparse.ArgumentParser) -> None`
  - `resolve_length_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> tuple[LengthSpec, ChapterSpec]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_story_length.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_story_length.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psalm_saga.story_length'`

- [ ] **Step 3: Write the implementation**

Create `psalm_saga/story_length.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_story_length.py -v`
Expected: PASS (28 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/story_length.py tests/unit/test_story_length.py
git commit -m "feat: add story length and chapter-count parsing module"
```

---

## Task 2: Wire `--length`/`--chapters` into `psalm-saga-batch`

**Files:**
- Modify: `psalm_saga/batch_cli.py`
- Test: `tests/unit/test_batch_cli.py`

**Interfaces:**
- Consumes: `story_length.{LengthSpec, ChapterSpec, add_length_arguments, resolve_length_arguments, format_length_directive}` from Task 1.
- Produces: `_build_story_instruction` gains a required `length_directive: str` parameter (last positional). `_parse_args`'s returned `Namespace` gains `.length`, `.chapters` (raw strings, possibly `None`), `.length_spec: LengthSpec`, `.chapter_spec: ChapterSpec`.

- [ ] **Step 1: Update and add the failing tests**

In `tests/unit/test_batch_cli.py`, add the import and update/add tests. First, update the existing two `_build_story_instruction` calls (around lines 71–82) to pass the new trailing argument, and add new tests for the flags:

```python
def test_build_story_instruction_for_scratch_mode() -> None:
    message = _build_story_instruction(
        1, 5, "scratch", "mixed", None, set(), "Story length directive: short story."
    )

    assert "story 1 of 5" in message
    assert "Mode: scratch" in message
    assert "Story length directive: short story." in message


def test_build_story_instruction_includes_existing_names() -> None:
    message = _build_story_instruction(
        2, 5, "context", "mixed", ["a spooky forest"], {"story-a"}, "Story length directive: novella."
    )

    assert "story-a" in message
```

Add these new tests anywhere in the file (near the other `_parse_args` tests):

```python
def test_parse_args_defaults_length_and_chapters() -> None:
    args = _parse_args(["--count", "1", "--mode", "scratch"])

    assert args.length_spec.category == "short-story"
    assert args.chapter_spec.mode == "auto"


def test_parse_args_resolves_explicit_length_and_chapters() -> None:
    args = _parse_args(
        ["--count", "1", "--mode", "scratch", "--length", "novella", "--chapters", "5"]
    )

    assert args.length_spec.category == "novella"
    assert args.chapter_spec.count == 5


def test_parse_args_rejects_invalid_length() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--count", "1", "--mode", "scratch", "--length", "not-a-category"])


def test_run_batch_includes_length_directive_in_every_story_instruction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    sent_messages: list[str] = []

    class _CapturingAgent:
        def stream(self, payload: Any, **_kwargs: Any) -> Iterator[Any]:
            sent_messages.append(payload["messages"][0]["content"])
            n = len(sent_messages)
            final = stories_dir(settings, session_id) / f"story-{n}.md"
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_text(f"# Story {n}\n", encoding="utf-8")
            return iter(())

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _CapturingAgent())

    args = _parse_args(
        ["--count", "1", "--mode", "scratch", "--session", session_id, "--length", "novella"]
    )
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(sent_messages) == 1
    assert "Story length directive: novella" in sent_messages[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_batch_cli.py -v`
Expected: FAIL — `_build_story_instruction() takes 6 positional arguments but 7 were given`, `AttributeError: 'Namespace' object has no attribute 'length_spec'`, and the new `--length`/`--chapters` tests fail similarly.

- [ ] **Step 3: Write the implementation**

In `psalm_saga/batch_cli.py`, add the import alongside the existing `psalm_saga.batch_session` import block:

```python
from psalm_saga.story_length import add_length_arguments, format_length_directive, resolve_length_arguments
```

In `_parse_args`, add the two flags right after the `--combine` argument (before `--session`):

```python
    parser.add_argument(
        "--combine", choices=["mixed", "separate"], default=None,
        help="How multiple inputs map onto --count stories. Forced to 'separate' for --mode variant.",
    )
    add_length_arguments(parser)
    parser.add_argument(
        "--session",
```

Then, right before the `return args` line, resolve the two flags into specs stored on the namespace:

```python
    if args.mode == "variant":
        if args.combine == "mixed":
            parser.error("--combine mixed is not valid with --mode variant")
        args.combine = "separate"
    elif args.combine is None:
        args.combine = "mixed"

    args.length_spec, args.chapter_spec = resolve_length_arguments(parser, args)

    return args
```

Update `_build_story_instruction`'s signature and body to take and include the directive:

```python
def _build_story_instruction(  # noqa: PLR0913, PLR0917
    story_index: int,
    count: int,
    mode: str,
    combine: str,
    inputs: list[str] | list[VariantSource] | None,
    existing_names: set[str],
    length_directive: str,
) -> str:
    if mode == "variant":
        inputs_desc = json.dumps(
            [
                {
                    "source": str(source.source_path),
                    "dimensions": list(source.dimensions),
                    "content": source.content,
                }
                for source in inputs or []
            ]
        )
    elif mode == "scratch":
        inputs_desc = "(none — invent freely)"
    else:
        inputs_desc = json.dumps(inputs)

    return (
        f"Generate story {story_index} of {count}. Mode: {mode}. "
        f"Combine: {combine}. Inputs: {inputs_desc}. "
        f"Existing names in this session: {sorted(existing_names)}. "
        f"{length_directive} "
        "Use the batch-story-generation skill."
    )
```

Finally, in `run_batch`, compute the directive once and pass it through the per-story call site:

```python
def run_batch(settings: Settings, args: argparse.Namespace, console: Console) -> None:
    inputs = _resolve_inputs(args)
    length_directive = format_length_directive(args.length_spec, args.chapter_spec)

    session_id = args.session_id or generate_session_id()
```

and update the call inside the `while` loop:

```python
            message = _build_story_instruction(
                done + 1, args.count, args.mode, args.combine, story_inputs, names, length_directive
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_batch_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/batch_cli.py tests/unit/test_batch_cli.py
git commit -m "feat: thread --length/--chapters into psalm-saga-batch's per-story instructions"
```

---

## Task 3: Wire `--length`/`--chapters` into interactive `psalm-saga`

**Files:**
- Modify: `psalm_saga/cli.py`
- Create: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `story_length.{add_length_arguments, resolve_length_arguments, format_length_directive}` from Task 1.
- Produces: `_run_one_session` gains a required `length_directive: str` parameter (last positional). `_parse_args`'s returned `Namespace` gains `.length_spec`, `.chapter_spec` same as Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli.py`:

```python
"""Tests for `psalm_saga.cli`'s argument parsing and the length-directive
injection into `build_agent`'s `system_prompt` for a fresh vs. resumed
session — the pieces that don't need a real model or terminal.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from psalm_saga import cli
from psalm_saga.cli import _parse_args, _run_one_session
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


def test_parse_args_defaults_length_and_chapters() -> None:
    args = _parse_args([])

    assert args.length_spec.category == "short-story"
    assert args.chapter_spec.mode == "auto"


def test_parse_args_resolves_explicit_length_and_chapters() -> None:
    args = _parse_args(["--length", "novella", "--chapters", "5"])

    assert args.length_spec.category == "novella"
    assert args.chapter_spec.count == 5


def test_parse_args_rejects_invalid_length() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--length", "not-a-category"])


class _ImmediatelyDoneSession:
    """Fakes `prompt_toolkit.PromptSession`: the first `.prompt()` call
    raises `EOFError`, so `run_session` exits right after `_run_one_session`
    starts it — enough to exercise `_run_one_session` without a real
    terminal.
    """

    def prompt(self, *_args: Any, **_kwargs: Any) -> str:
        raise EOFError


class _FakeState:
    values: dict[str, Any] = {}


class _FakeAgent:
    def get_state(self, _config: Any) -> _FakeState:
        return _FakeState()


@contextmanager
def _fake_checkpointer(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    yield None


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def test_run_one_session_injects_length_directive_for_a_fresh_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_a: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent()

    monkeypatch.setattr(cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(cli, "build_agent", fake_build_agent)

    directive = "Story length directive: novella, target 17,500-39,999 words. Chapter count: auto."
    _run_one_session(settings, "session-1", Console(), _ImmediatelyDoneSession(), directive)

    assert captured_kwargs["system_prompt"] == directive


def test_run_one_session_omits_length_directive_for_a_resumed_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    session_directory(settings, session_id).mkdir(parents=True)
    captured_kwargs: dict[str, Any] = {}

    def fake_build_agent(*_a: Any, **kwargs: Any) -> _FakeAgent:
        captured_kwargs.update(kwargs)
        return _FakeAgent()

    monkeypatch.setattr(cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(cli, "build_agent", fake_build_agent)

    directive = "Story length directive: novella, target 17,500-39,999 words. Chapter count: auto."
    _run_one_session(settings, session_id, Console(), _ImmediatelyDoneSession(), directive)

    assert captured_kwargs["system_prompt"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cli.py -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'length_spec'`, and `_run_one_session() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3: Write the implementation**

In `psalm_saga/cli.py`, add the import alongside the other `psalm_saga` imports:

```python
from psalm_saga.stream_renderer import StreamRenderer, extract_text, extract_tool_call_lines
from psalm_saga.story_length import add_length_arguments, format_length_directive, resolve_length_arguments
```

In `_parse_args`, add the two flags right after `--model` (before `--no-banner`):

```python
    parser.add_argument(
        "--model",
        dest="model",
        default=None,
        help="Override the main-loop model (e.g. anthropic:claude-sonnet-4-6, "
        "openai:gpt-4o). Overrides PSALM_SAGA_AGENT__ORCHESTRATION_MODEL_NAME.",
    )
    add_length_arguments(parser)
    parser.add_argument(
        "--no-banner",
```

At the end of `_parse_args`, resolve the flags before returning:

```python
    args = parser.parse_args(argv)
    args.length_spec, args.chapter_spec = resolve_length_arguments(parser, args)
    return args
```

(This replaces the current bare `return parser.parse_args(argv)` — split it into the two lines above.)

Update `_run_one_session`'s signature and body to accept and use the directive, applying it only when this is a fresh session:

```python
def _run_one_session(
    settings: Settings,
    session_id: str,
    console: Console,
    prompt_session: PromptSession,
    length_directive: str,
) -> str:
    """Open this session's checkpointer, build its agent, replay history if
    resuming, and run the interactive loop — all within one `with` block so
    the SQLite connection is always closed on the way out, however the loop
    ends (normal exit, `/reset`, or an exception).

    `length_directive` (from `--length`/`--chapters`, resolved in
    `_parse_args`) is only passed into the agent's `system_prompt` for a
    brand-new session — a resumed session's length dimension is either
    already decided or already mid-conversation, and re-injecting it risks
    contradicting a choice the human partner already made.
    """
    is_resuming = session_directory(settings, session_id).exists()
    system_prompt = "" if is_resuming else length_directive

    with open_sqlite_checkpointer(settings, session_id) as checkpointer:
        agent = build_agent(
            settings, session_id=session_id, checkpointer=checkpointer, system_prompt=system_prompt
        )

        console.print(f"[dim]Session directory:[/dim] {session_directory(settings, session_id)}\n")

        if is_resuming:
            _replay_history(agent, {"configurable": {"thread_id": session_id}}, console)

        return run_session(agent, session_id, console, prompt_session)
```

Update `main` to compute the directive and pass it into the loop's call site — only these lines change; the rest of the `while True:` loop body below (`if outcome == "exit": return`, the `/reset` handling, and the trailing `console.print`) stays exactly as it is today:

```python
    prompt_session = _build_prompt_session(settings, persist_history=not args.no_history)
    session_id = args.session_id or generate_session_id()
    length_directive = format_length_directive(args.length_spec, args.chapter_spec)
    console.print(f"[dim]Length target:[/dim] {length_directive}\n")

    while True:
        outcome = _run_one_session(settings, session_id, console, prompt_session, length_directive)
        # unchanged from here: if outcome == "exit": return; the /reset
        # branch that regenerates session_id and loops.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/cli.py tests/unit/test_cli.py
git commit -m "feat: inject --length/--chapters directive for fresh interactive sessions"
```

---

## Task 4: Length-and-chapters reference file + `story-brainstorming` skill edits

**Files:**
- Create: `psalm_saga/skills/story-brainstorming/references/length-and-chapters.md`
- Modify: `psalm_saga/skills/story-brainstorming/SKILL.md`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- None (skill markdown content only; no Python interfaces).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_skill_content.py`:

```python
def test_length_and_chapters_reference_exists_with_full_taxonomy() -> None:
    reference = (
        SKILLS_DIR / "story-brainstorming" / "references" / "length-and-chapters.md"
    ).read_text(encoding="utf-8")

    for label in ("Drabble", "Flash Fiction", "Short Story", "Novelette", "Novella", "Novel", "Epic"):
        assert label in reference
    assert "1,500" in reference  # the ~1,500-5,000 words/chapter novel norm
    assert "auto" in reference.lower()


def test_story_brainstorming_treats_a_length_directive_as_locked() -> None:
    body = _read_skill("story-brainstorming")

    assert "length-and-chapters.md" in body
    assert "length directive" in body.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_skill_content.py -v`
Expected: FAIL — `FileNotFoundError` for the reference file, and the new `story-brainstorming` assertions fail (no match in the current body).

- [ ] **Step 3: Write the implementation**

Create `psalm_saga/skills/story-brainstorming/references/length-and-chapters.md`:

```markdown
# Length and Chapter Count — reference

Read this in `story-brainstorming` Step 1 the first time a story's length
comes up in a session, and again in `writing-story-plans` Step 2 when
deciding a chapter count in "auto" mode. It has two parts: the length
taxonomy `--length` resolves against, and the chapter-count heuristic — a
set of stylistic norms to weigh, not a formula to apply mechanically.

## Length Taxonomy

| Category | Range (words) |
|---|---|
| Drabble | exactly 100 |
| Flash Fiction | 1–999 |
| Short Story | 1,000–7,499 |
| Novelette | 7,500–17,499 |
| Novella | 17,500–39,999 |
| Novel | 40,000–149,999 (typically 50,000–110,000; literary/commercial fiction often lands 70,000–90,000) |
| Epic / Doorstopper | loosely, well north of 150,000 |

A session's `--length` flag (or a length mentioned in conversation, for an
interactive session with no flag) resolves to one of these categories, or
to a custom word count/range that doesn't name a category at all — either
way, the target this reference informs is the same: a word count or range
to write toward.

## Chapter Count Guidance

Chapters are a formatting and pacing choice layered on top of the word
count, not something every story needs. Use the resolved length target as
the primary signal:

- **Drabble, Flash Fiction, Short Story, Novelette**: no formal chapters.
  Continuous prose, optionally broken by a few scene dividers for a pacing
  beat — never numbered or titled chapters at these lengths.
- **Novella**: a genuine judgment call based on pacing. Often has no
  chapters at all; when it does, it's usually just a handful — roughly 3
  to 10.
- **Novel**: the first length where chapters become a real convention —
  but still no fixed rule. A novel could be 5 long chapters or 80 short
  ones. Where an author does chapter it, roughly 1,500–5,000 words per
  chapter is a common stylistic norm worth considering, not a
  requirement — plenty of successful novels ignore it entirely (some
  authors write 800-word chapters, others 10,000-word ones).
- **Epic / Doorstopper**: essentially always chaptered at this length.
  Start from the Novel guidance above and the resolved word target.

When chapter count is "auto" (no explicit `--chapters` value), decide it
using this guidance and the resolved word target, and record the
reasoning in one line in the plan — e.g. "Chapter count: 6 — auto,
~4,000 words/chapter target for this ~25,000-word novel."
```

In `psalm_saga/skills/story-brainstorming/SKILL.md`, replace Step 1 of the Process:

```markdown
1. **Premise.** Ask what the person is trying to write and why: audience, genre, what a satisfying read *feels* like when it's done. For length: if a length directive was already injected into this session (a `--length`/`--chapters` flag resolved at startup), state it back rather than asking — e.g. "This session is targeting a novella (17,500–39,999 words)." — and treat it as decided; the conversation can still revise it later like any other spec choice. Otherwise ask about length as usual, defaulting to short story (1,000–7,499 words) if the person has no strong preference. Read `references/length-and-chapters.md` the first time length comes up in a session. Don't skip to dimensions before the premise is clear.
```

(This replaces the current single-sentence Step 1.)

In the same file's `## Autonomous Mode` section, insert a new paragraph right after the "**Decide, don't ask.**" paragraph and before the "- **Scratch:**" bullet list:

```markdown
**Length directive.** The per-story instruction message may include a
`Story length directive: ...` line. Treat it exactly like a
template-locked dimension: state the resolved length (and chapter count,
if explicit) back in the spec's Premise notes, and never re-decide it.
When the chapter count is "auto", read `references/length-and-chapters.md`
now so `writing-story-plans` has the right context later.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_content.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/story-brainstorming/references/length-and-chapters.md \
        psalm_saga/skills/story-brainstorming/SKILL.md \
        tests/unit/test_skill_content.py
git commit -m "docs: add length-and-chapters reference and lock directive handling in story-brainstorming"
```

---

## Task 5: `writing-story-plans` chapter-count handling

**Files:**
- Modify: `psalm_saga/skills/writing-story-plans/SKILL.md`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- None (skill markdown content only).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_skill_content.py`:

```python
def test_writing_story_plans_decides_chapter_count_from_directive_or_auto() -> None:
    body = _read_skill("writing-story-plans")

    assert "length-and-chapters.md" in body
    assert "chapter-count directive" in body.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_skill_content.py::test_writing_story_plans_decides_chapter_count_from_directive_or_auto -v`
Expected: FAIL (no match in the current `writing-story-plans/SKILL.md`)

- [ ] **Step 3: Write the implementation**

In `psalm_saga/skills/writing-story-plans/SKILL.md`, insert a new bullet into Step 2's list, immediately after the paragraph that begins "**Write the whole-story plan**..." and before the existing "**Don't inflate a spec choice...**" bullet:

```markdown
   - **Decide the chapter count first.** Check for a chapter-count directive (a `--chapters` value resolved at session/run startup, carried alongside the length directive from `story-brainstorming`'s Premise notes). If explicit, use it as given — never re-decide it. If `auto` (the default), read `../story-brainstorming/references/length-and-chapters.md` and decide based on the resolved length target, recording the reasoning in one line, e.g. "Chapter count: 6 — auto, ~4,000 words/chapter target for this ~25,000-word novel." For a length target in the drabble-through-novelette range, write a one-line note instead of a numbered chapter list: "No formal chapters — continuous prose, N scene breaks."
```

In the same file's `## Autonomous Mode` section, insert a new paragraph right after the "**Skip Step 4's sign-off.**" paragraph:

```markdown
**Chapter-count directive.** As with a length directive, a locked
`--chapters` value must be used exactly as given, never re-decided —
same treatment as any other locked input in this mode.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_content.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/writing-story-plans/SKILL.md tests/unit/test_skill_content.py
git commit -m "docs: teach writing-story-plans to honor a chapter-count directive or resolve auto"
```

---

## Task 6: `batch-story-generation` documents the length directive line

**Files:**
- Modify: `psalm_saga/skills/batch-story-generation/SKILL.md`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- None (skill markdown content only).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_skill_content.py`:

```python
def test_batch_story_generation_documents_the_length_directive_line() -> None:
    body = _read_skill("batch-story-generation")

    assert "length directive" in body.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_skill_content.py::test_batch_story_generation_documents_the_length_directive_line -v`
Expected: FAIL (no match in the current `batch-story-generation/SKILL.md`)

- [ ] **Step 3: Write the implementation**

In `psalm_saga/skills/batch-story-generation/SKILL.md`, insert a new paragraph into the "## What you'll receive" section, immediately after the blockquoted example message and before the paragraph beginning "`Combine: separate` means...":

```markdown
The message may also include a `Story length directive: ...` line (from
the run's `--length`/`--chapters` flags) — treat it as locked input
exactly like `Mode`/`Combine`/`Inputs`: `story-brainstorming` and
`writing-story-plans` state it back rather than deciding it themselves.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_skill_content.py -v`
Expected: PASS (full file, all tests from Tasks 4–6 included)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/batch-story-generation/SKILL.md tests/unit/test_skill_content.py
git commit -m "docs: document the length directive line in batch-story-generation"
```

---

## Final verification

- [ ] Run the full unit test suite: `pytest tests/unit -v` — expect all tests green, including every test added across Tasks 1–6.
- [ ] Run `ruff check psalm_saga tests` — expect no new lint findings in `story_length.py`, `batch_cli.py`, `cli.py`, or the two new/modified test files.
- [ ] Manually sanity-check the CLI help text: `psalm-saga --help` and `psalm-saga-batch --help` (or `python -m psalm_saga.cli --help` / `python -m psalm_saga.batch_cli --help` if the console scripts aren't installed) both show `--length` and `--chapters` with the taxonomy listed.
