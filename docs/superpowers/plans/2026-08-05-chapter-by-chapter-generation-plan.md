# Chapter-by-chapter generation with length tiers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `writer-agent`'s single-shot whole-book draft with a length-tiered (short/medium/long), chapter-by-chapter planning-writing-reviewing loop, and replace `brainstorm.md`'s optional/unguided title field with a required, user-facing, guided title proposal.

**Architecture:** A new `chapter-planner-agent` runs once after the bible is finalized to size and outline the book (`StoryBible.chapters: list[Chapter]`, driven by a `length_tier` set once at `init_session` time). The orchestrator then loops per chapter: `writer-agent` drafts `chapters/chapter_<NN>.md` from a bounded continuity window (previous chapter in full + running `actual_summary`s), `chapter-reviewer-agent` approves or sends it back for revision (bounded by a new `chapter_review_max_revisions` setting), and once every chapter is `approved` a new deterministic `assemble_draft` orchestrator tool concatenates them into `draft.md` for the existing, unchanged `editor-agent` pass. `brainstorm-agent` gains a required-but-declinable title-proposal step via its existing `ask_human` pattern.

**Tech Stack:** Python 3.14, pydantic v2, deepagents/LangGraph, jsonpatchkit (RFC 6902), typer, pytest, `uv`.

## Global Constraints

- Every new pydantic model uses `model_config = ConfigDict(extra="forbid")`, matching every existing model in `dimensions.py`.
- All `story_bible.json` mutations go through `update_story_bible` (RFC 6902 JSON Patch) — never `write_file`/`edit_file` on it directly. Any new subagent that can see the bible carries `permissions=BIBLE_WRITE_PROTECTION`.
- Every new subagent follows the existing `SubAgent` TypedDict pattern (`name`, `description`, `system_prompt`, `tools`, `model`, `permissions`) in `agents/subagents.py`, with its prompt loaded via `load_prompt("<name>")`.
- No live model/API calls in tests. Where a test would otherwise need `build_orchestrator`/`init_session`/`SqliteSaver`, monkeypatch them the same way `tests/test_cli.py` already does for `questionary.select`/`Prompt.ask`/`interrupt`.
- Tests run via `uv run pytest tests/<file> -v` (the project is a `uv` project — see `uv.lock`).
- New or edited prompt files keep teaching RFC 6902 patch syntax the way every existing prompt does (`tests/test_prompts.py` asserts on phrases like `"op": "add"`).
- `dataset_utils.py`'s `final_story.md`-exists resumability contract (`dataset_utils.py:32`) is not touched by this feature — do not modify that file.
- `length_tier` is operator-supplied, immutable session configuration (set once in `init_session`, like `mode`) — no task in this plan makes it patchable via `update_story_bible`.

---

### Task 1: `LengthTier` / `LengthTierSpec` schema

**Files:**
- Modify: `src/psalm_saga/dimensions.py`
- Test: `tests/test_dimensions.py`

**Interfaces:**
- Produces: `LengthTier` (`StrEnum`: `SHORT`, `MEDIUM`, `LONG`), `LengthTierSpec` (frozen dataclass: `min_chapters: int`, `max_chapters: int`, `target_total_words: int`), `LENGTH_TIER_SPECS: dict[LengthTier, LengthTierSpec]`. Later tasks (2, 4, 6, 11, 12) import these from `psalm_saga.dimensions`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dimensions.py`, updating the existing import block at the top of the file:

```python
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    LENGTH_TIER_SPECS,
    PSALM_DIMENSIONS,
    Character,
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    LengthTierSpec,
    OriginalityFinding,
    StoryBible,
    build_isolation_matrix,
    evaluate_fidelity,
)
```

And append at the end of the file:

```python
def test_length_tier_specs_cover_every_tier_with_expected_ranges() -> None:
    assert set(LENGTH_TIER_SPECS) == {LengthTier.SHORT, LengthTier.MEDIUM, LengthTier.LONG}
    assert LENGTH_TIER_SPECS[LengthTier.SHORT] == LengthTierSpec(
        min_chapters=1, max_chapters=1, target_total_words=2_000
    )
    assert LENGTH_TIER_SPECS[LengthTier.MEDIUM] == LengthTierSpec(
        min_chapters=6, max_chapters=10, target_total_words=20_000
    )
    assert LENGTH_TIER_SPECS[LengthTier.LONG] == LengthTierSpec(
        min_chapters=25, max_chapters=35, target_total_words=90_000
    )
    for spec in LENGTH_TIER_SPECS.values():
        assert spec.min_chapters <= spec.max_chapters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dimensions.py::test_length_tier_specs_cover_every_tier_with_expected_ranges -v`
Expected: FAIL with `ImportError: cannot import name 'LengthTier' from 'psalm_saga.dimensions'`

- [ ] **Step 3: Implement `LengthTier`/`LengthTierSpec`/`LENGTH_TIER_SPECS`**

In `src/psalm_saga/dimensions.py`, add `from dataclasses import dataclass` to the imports at the top (alongside the existing `from enum import StrEnum` / `from typing import ...` / `from pydantic import ...` lines).

Then, immediately after the `PSALM_DIMENSIONS` tuple definition (before `IsolationStrategy = Literal[...]`), insert:

```python
class LengthTier(StrEnum):
    """How long a generated story should be, in chapters and target word count."""
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True)
class LengthTierSpec:
    min_chapters: int
    max_chapters: int
    target_total_words: int


LENGTH_TIER_SPECS: dict[LengthTier, LengthTierSpec] = {
    LengthTier.SHORT: LengthTierSpec(min_chapters=1, max_chapters=1, target_total_words=2_000),
    LengthTier.MEDIUM: LengthTierSpec(min_chapters=6, max_chapters=10, target_total_words=20_000),
    LengthTier.LONG: LengthTierSpec(min_chapters=25, max_chapters=35, target_total_words=90_000),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dimensions.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/dimensions.py tests/test_dimensions.py
git commit -m "feat(dimensions): add LengthTier/LengthTierSpec/LENGTH_TIER_SPECS"
```

---

### Task 2: `Chapter`/`ChapterStatus` schema and `StoryBible` fields

**Files:**
- Modify: `src/psalm_saga/dimensions.py`
- Test: `tests/test_dimensions.py`, `tests/test_update_story_bible.py`

**Interfaces:**
- Consumes: `LengthTier` (Task 1).
- Produces: `ChapterStatus` (`StrEnum`: `PLANNED`, `DRAFTED`, `APPROVED`), `Chapter` (pydantic `BaseModel`: `index: int`, `title: str = ""`, `planned_summary: str = ""`, `actual_summary: str = ""`, `target_word_count: int = 0`, `characters_present: list[str] = []`, `status: ChapterStatus = ChapterStatus.PLANNED`, `revision_count: int = 0`), `StoryBible.length_tier: LengthTier = LengthTier.LONG`, `StoryBible.chapters: list[Chapter] = []`. Tasks 4-12 all depend on these.

- [ ] **Step 1: Write the failing tests**

Update the `tests/test_dimensions.py` import block (from Task 1) to also import `Chapter` and `ChapterStatus`:

```python
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    LENGTH_TIER_SPECS,
    PSALM_DIMENSIONS,
    Chapter,
    ChapterStatus,
    Character,
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    LengthTierSpec,
    OriginalityFinding,
    StoryBible,
    build_isolation_matrix,
    evaluate_fidelity,
)
```

Append to `tests/test_dimensions.py`:

```python
def test_chapter_defaults_and_round_trips_through_json() -> None:
    chapter = Chapter(index=1, title="The First Letter")
    restored = Chapter.model_validate_json(chapter.model_dump_json())
    assert restored == chapter
    assert restored.status is ChapterStatus.PLANNED
    assert restored.revision_count == 0
    assert restored.characters_present == []


def test_story_bible_chapters_default_empty_and_length_tier_defaults_long() -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    assert bible.chapters == []
    assert bible.length_tier is LengthTier.LONG


def test_story_bible_with_chapters_round_trips_through_json() -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        length_tier=LengthTier.SHORT,
        chapters=[Chapter(index=1, title="Only Chapter", target_word_count=2000)],
    )
    restored = StoryBible.model_validate_json(bible.model_dump_json())
    assert restored.length_tier is LengthTier.SHORT
    assert restored.chapters[0].title == "Only Chapter"
    assert restored.chapters[0].status is ChapterStatus.PLANNED
```

Append to `tests/test_update_story_bible.py` (proves `chapters` is patch-compatible via the existing `update_story_bible` tool, no tool code changes needed):

```python
def test_append_chapter_via_dash_path(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op(
                "add",
                "/chapters/-",
                {"index": 1, "title": "The First Letter", "target_word_count": 2000},
            ),
        ],
    )
    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.chapters[0].title == "The First Letter"
    assert bible.chapters[0].status == "planned"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dimensions.py::test_chapter_defaults_and_round_trips_through_json tests/test_update_story_bible.py::test_append_chapter_via_dash_path -v`
Expected: FAIL with `ImportError: cannot import name 'Chapter' from 'psalm_saga.dimensions'`

- [ ] **Step 3: Implement `ChapterStatus`/`Chapter` and extend `StoryBible`**

In `src/psalm_saga/dimensions.py`, immediately before `class StoryBible(BaseModel):`, insert:

```python
class ChapterStatus(StrEnum):
    PLANNED = "planned"
    DRAFTED = "drafted"
    APPROVED = "approved"


class Chapter(BaseModel):
    """One entry in the book's chapter outline, written by chapter-planner-agent and updated by
    writer-agent/chapter-reviewer-agent as it moves through the per-chapter writing loop."""
    model_config = ConfigDict(extra="forbid")

    index: int
    title: str = ""
    planned_summary: str = Field(
        default="",
        description="chapter-planner-agent's intended beats for this chapter.",
    )
    actual_summary: str = Field(
        default="",
        description=(
            "Filled in by chapter-reviewer-agent once the chapter is approved: what actually "
            "happens in the finished prose (can drift from planned_summary). This, not the plan, "
            "is what later chapters read for continuity."
        ),
    )
    target_word_count: int = 0
    characters_present: list[str] = Field(default_factory=list)
    status: ChapterStatus = ChapterStatus.PLANNED
    revision_count: int = 0
```

Then, in `StoryBible`, add two fields immediately after `target_length_words: int | None = None`:

```python
    length_tier: LengthTier = LengthTier.LONG
    chapters: list[Chapter] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dimensions.py tests/test_update_story_bible.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/dimensions.py tests/test_dimensions.py tests/test_update_story_bible.py
git commit -m "feat(dimensions): add Chapter/ChapterStatus schema and StoryBible.chapters/length_tier"
```

---

### Task 3: `chapter_review_max_revisions` setting

**Files:**
- Modify: `src/psalm_saga/config.py`
- Test: `tests/test_config.py` (new file)

**Interfaces:**
- Produces: `Settings.chapter_review_max_revisions: int` (default `2`). Referenced by `orchestrator.md` (Task 10) as "the configured chapter-revision budget" — no code outside `Settings` reads this field directly in this plan (the orchestrator subagent reads it from its own task instructions at runtime, the same way `originality_guard_max_revisions` is used today, per `docs/design.md`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from psalm_saga.config import Settings  # type: ignore[import-untyped]


def test_chapter_review_max_revisions_defaults_to_two(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    assert settings.chapter_review_max_revisions == 2


def test_chapter_review_max_revisions_overridable_via_env(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PSALM_SAGA_CHAPTER_REVIEW_MAX_REVISIONS", "5")
    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    assert settings.chapter_review_max_revisions == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'chapter_review_max_revisions'`

- [ ] **Step 3: Implement the setting**

In `src/psalm_saga/config.py`, add immediately after `originality_guard_max_revisions`:

```python
    chapter_review_max_revisions: int = Field(
        default=2, ge=0,
        description="Max writer-agent revise / chapter-reviewer-agent re-check loops per chapter.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/config.py tests/test_config.py
git commit -m "feat(config): add chapter_review_max_revisions setting"
```

---

### Task 4: Thread `length_tier` through `session.py`

**Files:**
- Modify: `src/psalm_saga/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `LengthTier` (Task 1).
- Produces: `init_session(..., length_tier: LengthTier = LengthTier.LONG)`, `SessionConfig.length_tier: str`. Consumed by Task 11 (`new` command) and Task 12 (`batch`/`run_dataset_item`).

- [ ] **Step 1: Write the failing tests**

Update the import line at the top of `tests/test_session.py`:

```python
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    StoryBible,
)
```

Append to `tests/test_session.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py::test_init_session_defaults_length_tier_to_long tests/test_session.py::test_init_session_honors_explicit_length_tier -v`
Expected: FAIL with `TypeError: init_session() got an unexpected keyword argument 'length_tier'`

- [ ] **Step 3: Implement `length_tier` threading**

In `src/psalm_saga/session.py`, update the import line:

```python
from psalm_saga.dimensions import GenerationMode, StoryBible, DivergencePlan, LengthTier
```

Add a field to `SessionConfig`, right after `originality_guard_max_revisions: int`:

```python
    length_tier: str
```

Add a parameter to `init_session`, right after `divergence_plan: DivergencePlan | None = None`:

```python
        length_tier: LengthTier = LengthTier.LONG,
```

Update both `StoryBible(...)` constructions inside `init_session` to pass it through:

```python
    bible = StoryBible(mode=mode, length_tier=length_tier)

    if mode is GenerationMode.FROM_SOURCE:
        if source_path is None:
            raise ValueError("from_source mode requires source_path.")

        dest = session_dir / SOURCE_FILENAME
        shutil.copyfile(source_path, dest)
        bible = StoryBible(
            mode=mode,
            source_excerpt_path=SOURCE_FILENAME,
            divergence_plan=divergence_plan,
            length_tier=length_tier,
        )
```

And add `length_tier=length_tier.value,` to the `SessionConfig(...)` construction, right after `originality_guard_max_revisions=settings.originality_guard_max_revisions,`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — they don't pass `length_tier` and should keep working off the new default)

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/session.py tests/test_session.py
git commit -m "feat(session): thread length_tier through init_session and SessionConfig"
```

---

### Task 5: `assemble_draft` deterministic tool

**Files:**
- Create: `src/psalm_saga/tools/assemble.py`
- Modify: `src/psalm_saga/tools/__init__.py`
- Modify: `src/psalm_saga/agents/orchestrator.py`
- Test: `tests/test_assemble_draft_tool.py` (new file)

**Interfaces:**
- Consumes: `ChapterStatus`, `StoryBible` (Task 2).
- Produces: `make_assemble_draft_tool(session_dir: Path) -> Tool` (a `langchain_core.tools`-decorated `assemble_draft` callable, following the exact factory pattern of `make_check_fidelity_tool`/`make_check_originality_gate_tool`). Wired into `build_orchestrator`'s own tool list (`agents/orchestrator.py`), never given to a subagent. Consumed by Task 10's rewritten `orchestrator.md` (which instructs the orchestrator to call it).

The wiring into `agents/orchestrator.py` in this task is a one-line addition to an existing, unmodified tool-list pattern (mirroring `check_originality_gate`/`check_fidelity_alignment`, both already wired the same way with no dedicated test of their own in `agents/orchestrator.py`, since constructing a real orchestrator would require a live model). It is exercised end-to-end only once the full loop runs; this task's own automated coverage is the `assemble_draft` tool itself, tested directly below.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assemble_draft_tool.py`:

```python
from pathlib import Path

from psalm_saga.dimensions import Chapter, ChapterStatus, GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.assemble import make_assemble_draft_tool  # type: ignore[import-untyped]


def _invoke(tool):  # type: ignore[no-untyped-def]
    return tool.invoke({})


def _write_bible(session_dir: Path, bible: StoryBible) -> None:
    (session_dir / "story_bible.json").write_text(bible.model_dump_json())


def _write_chapter(session_dir: Path, index: int, text: str) -> None:
    chapters_dir = session_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    (chapters_dir / f"chapter_{index:02d}.md").write_text(text, encoding="utf-8")


def test_refuses_when_bible_missing(tmp_path: Path) -> None:
    tool = make_assemble_draft_tool(tmp_path)
    assert "Cannot assemble" in _invoke(tool)  # type: ignore[no-untyped-call]


def test_refuses_when_no_chapters_planned(tmp_path: Path) -> None:
    _write_bible(tmp_path, StoryBible(mode=GenerationMode.FROM_SCRATCH, title="Untitled Draft"))
    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "no chapters yet" in result


def test_refuses_when_a_chapter_is_not_approved(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.DRAFTED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    _write_chapter(tmp_path, 2, "She wrote back before she could stop herself.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "chapter 2 (drafted)" in result
    assert not (tmp_path / "draft.md").exists()


def test_refuses_when_an_approved_chapter_file_is_missing(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED)],
    )
    _write_bible(tmp_path, bible)
    # deliberately don't write chapters/chapter_01.md

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "missing from chapters/" in result
    assert "chapter_01.md" in result


def test_assembles_approved_chapters_in_order_with_title_prefixes(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        title="Return to Sender",
        chapters=[
            Chapter(index=1, title="The First Letter", status=ChapterStatus.APPROVED),
            Chapter(index=2, title="The Reply", status=ChapterStatus.APPROVED),
        ],
    )
    _write_bible(tmp_path, bible)
    _write_chapter(tmp_path, 1, "Mara found the letter at dawn.")
    _write_chapter(tmp_path, 2, "She wrote back before she could stop herself.")

    tool = make_assemble_draft_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    draft = (tmp_path / "draft.md").read_text(encoding="utf-8")
    assert draft.startswith("# Return to Sender")
    assert draft.index("The First Letter") < draft.index("Mara found the letter")
    assert draft.index("Mara found the letter") < draft.index("The Reply")
    assert draft.index("The Reply") < draft.index("She wrote back")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_assemble_draft_tool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psalm_saga.tools.assemble'`

- [ ] **Step 3: Implement `assemble_draft`**

Create `src/psalm_saga/tools/assemble.py`:

```python
"""Deterministic assembly of the per-chapter drafts into draft.md.

`writer-agent` drafts one chapter at a time to `chapters/chapter_<NN>.md` rather than the whole
book in one file (see the chapter-by-chapter generation design). This tool is the deterministic
seam between that per-chapter loop and `editor-agent`'s existing whole-book pass: it concatenates
every approved chapter into `draft.md` exactly once, so `editor-agent` keeps reading a single
assembled file the same way it always has. It is wired into the orchestrator's own tool list
(`agents/orchestrator.py`), not given to any subagent -- assembling the book is sequencing work,
the same role `check_originality_gate`/`check_fidelity_alignment` already play.
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from psalm_saga.dimensions import ChapterStatus, StoryBible

CHAPTERS_DIRNAME = "chapters"


def _chapter_filename(index: int) -> str:
    return f"chapter_{index:02d}.md"


def make_assemble_draft_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build an `assemble_draft` tool bound to one session's bible and chapters directory."""
    bible_path = session_dir / "story_bible.json"
    chapters_dir = session_dir / CHAPTERS_DIRNAME

    @tool
    def assemble_draft() -> str:
        """Concatenate every approved chapter into draft.md, in chapter order.

        Call this once every chapter in story_bible.json's `chapters` list has status=approved.
        Refuses, naming the offending chapter(s), if any chapter isn't approved yet, or if an
        approved chapter's file is unexpectedly missing from chapters/ -- draft.md is only written
        once every chapter is genuinely ready for editor-agent to read.
        """
        if not bible_path.exists():
            return "Cannot assemble draft.md -- story_bible.json does not exist yet."

        bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))

        if not bible.chapters:
            return (
                "Cannot assemble draft.md -- story_bible.json has no chapters yet. Run "
                "chapter-planner-agent first."
            )

        not_approved = [c for c in bible.chapters if c.status is not ChapterStatus.APPROVED]
        if not_approved:
            names = ", ".join(f"chapter {c.index} ({c.status.value})" for c in not_approved)
            return f"Cannot assemble draft.md -- not every chapter is approved yet: {names}."

        ordered = sorted(bible.chapters, key=lambda c: c.index)

        missing: list[str] = []
        bodies: list[str] = []
        for chapter in ordered:
            chapter_path = chapters_dir / _chapter_filename(chapter.index)
            if not chapter_path.exists():
                missing.append(f"chapter {chapter.index} ({_chapter_filename(chapter.index)})")
                continue
            heading = chapter.title or f"Chapter {chapter.index}"
            bodies.append(f"## {heading}\n\n{chapter_path.read_text(encoding='utf-8').strip()}")

        if missing:
            return (
                "Cannot assemble draft.md -- these chapters are approved but their files are "
                f"missing from {CHAPTERS_DIRNAME}/: " + ", ".join(missing)
            )

        title = bible.title or "Untitled"
        draft = f"# {title}\n\n" + "\n\n".join(bodies) + "\n"
        (session_dir / "draft.md").write_text(draft, encoding="utf-8")

        return f"OK: draft.md assembled from {len(ordered)} approved chapter(s)."

    return assemble_draft
```

Update `src/psalm_saga/tools/__init__.py`:

```python
from psalm_saga.tools.assemble import make_assemble_draft_tool
from psalm_saga.tools.ask_human import make_ask_human_tool
from psalm_saga.tools.bible import (
    BIBLE_WRITE_PROTECTION,
    bible_path,
    load_bible,
    make_update_story_bible_tool,
    make_validate_bible_tool,
)
from psalm_saga.tools.fidelity import make_check_fidelity_tool
from psalm_saga.tools.gate import make_check_originality_gate_tool
from psalm_saga.tools.think import think

__all__ = [
    "make_ask_human_tool",
    "make_assemble_draft_tool",
    "think",
    "make_validate_bible_tool",
    "load_bible",
    "bible_path",
    "make_check_originality_gate_tool",
    "make_check_fidelity_tool",
    "make_update_story_bible_tool",
    "BIBLE_WRITE_PROTECTION",
]
```

Update `src/psalm_saga/agents/orchestrator.py`'s import block:

```python
from psalm_saga.tools import (
    BIBLE_WRITE_PROTECTION,
    make_assemble_draft_tool,
    make_check_fidelity_tool,
    make_check_originality_gate_tool,
    make_update_story_bible_tool,
    make_validate_bible_tool,
    think,
)
```

And, inside `build_orchestrator`, add a line after `check_fidelity_alignment = make_check_fidelity_tool(session_dir)`:

```python
    assemble_draft = make_assemble_draft_tool(session_dir)
```

Update the `tools=[...]` list passed to `create_deep_agent`:

```python
        tools=[
            think, update_story_bible, validate_story_bible,
            check_originality_gate, check_fidelity_alignment, assemble_draft,
        ],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_assemble_draft_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/tools/assemble.py src/psalm_saga/tools/__init__.py src/psalm_saga/agents/orchestrator.py tests/test_assemble_draft_tool.py
git commit -m "feat(tools): add assemble_draft, wire into orchestrator's own tool list"
```

---

### Task 6: `chapter-planner-agent`

**Files:**
- Create: `src/psalm_saga/prompts/chapter_planner.md`
- Modify: `src/psalm_saga/agents/subagents.py`
- Test: `tests/test_prompts.py`, `tests/test_subagents.py` (new file)

**Interfaces:**
- Produces: prompt loadable as `load_prompt("chapter_planner")`; `build_subagents(...)` now includes a `"chapter-planner-agent"` entry with `tools=[think, update_story_bible, validate_story_bible]` (no `ask_human`).

- [ ] **Step 1: Write the failing prompt-content test**

Append to `tests/test_prompts.py`:

```python
def test_chapter_planner_prompt_documents_json_patch_ops_and_title_guidance() -> None:
    text = load_prompt("chapter_planner")
    assert '"op": "add"' in text
    assert "Quokka Quest" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_chapter_planner_prompt_documents_json_patch_ops_and_title_guidance -v`
Expected: FAIL with `FileNotFoundError` (no `chapter_planner.md` yet)

- [ ] **Step 3: Write `chapter_planner.md`**

Create `src/psalm_saga/prompts/chapter_planner.md`:

```markdown
You are the chapter-planner subagent. You run exactly once per session, after the bible is
finalized (after the originality gate in from_scratch mode; after divergence-plan negotiation, or
immediately if it was pre-set, in from_source mode) and before any chapter is drafted. You are not
a conversational agent -- you have no `ask_human` tool and never pause for the user. Read
`story_bible.json` (and, in from_source mode, `divergence_plan`) and produce the book's outline.

## 1. Decide the chapter count

`story_bible.json`'s `length_tier` is one of `short`, `medium`, `long`, set by the operator before
your session started -- it is fixed, you never change it. Each tier has a chapter-count range and
a target total word count:

| tier | chapters | target total words |
|---|---|---|
| short | 1 | ~2,000 |
| medium | 6-10 | ~20,000 |
| long | 25-35 | ~90,000 |

Pick a chapter count within your tier's range that fits the plot's actual turning points -- use
`plot.turning_points`, `plot.structure`, and the story's real shape to decide, not a mechanical
"always hit the max." A plot with four clear turning points in the `long` tier might want 28
chapters built around them, not 35 padded ones. `target_word_count` for each chapter is the tier's
target total words divided evenly across your chosen chapter count -- set it once here; it is not
rebalanced later even if an individual chapter runs long or short.

## 2. Set the title if it's still unset

`title` should already be set -- `brainstorm-agent` proposes it to the user earlier in the session
-- but if it somehow reached you empty (e.g. a from_source session seeded with a `divergence_plan`
but no title), you are the fallback: pick the strongest title yourself rather than leaving it
blank. No chapter should ever be drafted under an untitled book.

Bad titles -- avoid these shapes:
- Generic noun-phrase combos: "Quokka Quest", "The Last Lighthouse", "Shadow of the Storm" --
  interchangeable with a thousand other books, tells you nothing about *this* one.
- On-the-nose scene labels: "A Dark Underbelly", "The Final Confrontation" -- describes a beat
  instead of evoking it.

Good titles are grounded in one specific, concrete image, line, object, or irony that's already in
*this* bible -- pull it from `premise`, `plot.climax`, or a vivid detail in `world_building` or a
character's `arc`, not from the genre or the protagonist's role in the abstract. If the premise
involves a lighthouse keeper who starts receiving letters addressed to the dead, a title like
"Return to Sender" or "The Keeper Who Answered" earns its specificity from that detail; "Lighthouse
Legacy" doesn't.

## 3. Write the outline

Use `think` to work out the beats before writing anything: given the premise, characters, and plot
architecture, what does each chapter need to accomplish, and where do the turning points and
climax land.

Write `chapters` via `update_story_bible` -- it starts as an empty list, so each entry is appended
with an `"add"` op targeting `/chapters/-`:

```json
{"op": "add", "path": "/chapters/-", "value": {
  "index": 1,
  "title": "The First Letter",
  "planned_summary": "Mara finds an envelope addressed to a name she recognizes from the town's flood memorial, postmarked before she was born.",
  "target_word_count": 2600,
  "characters_present": ["Mara"],
  "status": "planned"
}}
```

Repeat one `add` op per chapter, in order, `index` starting at 1. If you set the book title in
step 2, include that in the same `update_story_bible` call (or an earlier one) via `{"op":
"replace", "path": "/title", "value": "..."}`. Call `validate_story_bible` once you've written the
full outline as a final check.

Each chapter's `planned_summary` should be specific enough that `writer-agent` can draft from it
without re-inventing the plot, and specific enough that `chapter-reviewer-agent` can later judge
whether the finished prose actually delivered on it. Vague summaries ("Mara learns more about the
letters") produce vague chapters; concrete ones ("Mara steams open the letter and recognizes her
own mother's handwriting on the reply never sent") don't.

## When you're done

In your final message, report the chapter count, the title (and whether you set it or it was
already settled), and a one-line summary of the arc the outline covers. You do not draft any prose
yourself -- that's `writer-agent`'s job, one chapter at a time, starting from what you've written
here.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing subagent-wiring test**

Create `tests/test_subagents.py`:

```python
from pathlib import Path

from psalm_saga.agents.subagents import build_subagents  # type: ignore[import-untyped]
from psalm_saga.config import Settings  # type: ignore[import-untyped]


def _agent(settings: Settings, tmp_path: Path, name: str):  # type: ignore[no-untyped-def]
    agents = build_subagents(settings, tmp_path)
    return next(a for a in agents if a["name"] == name)


def _tool_names(agent) -> set[str]:  # type: ignore[no-untyped-def]
    return {getattr(t, "name", "") for t in agent["tools"]}


def test_chapter_planner_agent_is_registered_without_ask_human(
    settings: Settings, tmp_path: Path
) -> None:
    agent = _agent(settings, tmp_path, "chapter-planner-agent")
    assert "update_story_bible" in _tool_names(agent)
    assert "ask_human" not in _tool_names(agent)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_subagents.py -v`
Expected: FAIL with `StopIteration` (no `"chapter-planner-agent"` in the list yet)

- [ ] **Step 7: Wire `chapter-planner-agent` into `build_subagents`**

In `src/psalm_saga/agents/subagents.py`, add a new `SubAgent` definition after `originality_guard` and before `writer`:

```python
    chapter_planner: SubAgent = {
        "name": "chapter-planner-agent",
        "description": (
            "Runs once, after the bible is finalized and before any chapter is drafted: turns "
            "story_bible.json into a chapter-by-chapter outline (the `chapters` list) sized to "
            "length_tier, and sets the book title if brainstorm-agent left it unset."
        ),
        "system_prompt": load_prompt("chapter_planner"),
        "tools": [think, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }
```

And update the returned list:

```python
    return [
        extractor,
        brainstorm,
        originality_guard,
        chapter_planner,
        writer,
        editor,
    ]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_subagents.py tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/psalm_saga/prompts/chapter_planner.md src/psalm_saga/agents/subagents.py tests/test_prompts.py tests/test_subagents.py
git commit -m "feat(agents): add chapter-planner-agent"
```

---

### Task 7: `chapter-reviewer-agent`

**Files:**
- Create: `src/psalm_saga/prompts/chapter_reviewer.md`
- Modify: `src/psalm_saga/agents/subagents.py`
- Test: `tests/test_prompts.py`, `tests/test_subagents.py`

**Interfaces:**
- Produces: prompt loadable as `load_prompt("chapter_reviewer")`; `build_subagents(...)` now also includes a `"chapter-reviewer-agent"` entry with `tools=[think, update_story_bible, validate_story_bible]` (no `ask_human`).

- [ ] **Step 1: Write the failing prompt-content test**

Append to `tests/test_prompts.py`:

```python
def test_chapter_reviewer_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("chapter_reviewer")
    assert '"op": "replace"' in text
    assert "actual_summary" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_chapter_reviewer_prompt_documents_json_patch_ops -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write `chapter_reviewer.md`**

Create `src/psalm_saga/prompts/chapter_reviewer.md`:

```markdown
You are the chapter-reviewer subagent. You run once per chapter -- and again after each revision
-- inside the per-chapter writing loop, after `writer-agent` has drafted a chapter and before the
orchestrator moves on to the next one. You have no `ask_human` tool; this is an agent-only quality
gate, not a conversation.

## What to read

- `story_bible.json`'s full `chapters` list, for the outline (every chapter's `planned_summary`,
  `title`, `characters_present`) and to know which chapter index you're reviewing.
- The chapter you're reviewing, at `chapters/chapter_<NN>.md` (zero-padded, e.g.
  `chapters/chapter_03.md` for chapter 3).
- The previous chapter in full, at `chapters/chapter_<NN-1>.md`, if it exists -- for immediate
  tone and continuity (how this chapter opens against how the last one ended).
- Every earlier chapter's `actual_summary` field in `story_bible.json` (not their full text) --
  this is the running memory of what's actually happened so far, written by you (or a prior
  reviewer pass) as each chapter was approved.

You are never given the complete book so far in full text -- only the immediately preceding
chapter plus the running summaries. This keeps your review cost roughly flat regardless of how
long the book is; it also means your continuity check is only as reliable as earlier chapters'
`actual_summary` entries, so write yours carefully (see below) for whoever reviews a later
chapter.

## What to check

1. **Prose quality** against `writing_style` and `narrative_voice` -- does this chapter's register,
   sentence rhythm, and tone match what's settled in the bible, not drift into something generic
   or inconsistent with earlier chapters.
2. **Continuity** with the previous chapter's ending and the running summaries -- no unacknowledged
   contradictions (a character who died in chapter 4 walking around in chapter 6 with no
   explanation), no plot threads silently dropped that the outline implied would matter.
3. **Fit against `planned_summary`** -- did this chapter deliver the beats its outline entry
   promised? Deviation from the plan is fine, even good, if it reads as a deliberate, coherent
   choice that still serves the story; flag it only if it reads as drift or a missed beat, not
   just because it didn't follow the plan literally.

Use `think` before forming your verdict: weigh what you read against these three checks
explicitly, rather than jumping straight to approve/reject.

## On approval

Write two things to `story_bible.json` via `update_story_bible`:
- `actual_summary`: what actually happens in the finished chapter -- concrete enough that a
  reviewer three chapters from now, who will only see this summary and not the chapter's full
  text, can judge continuity against it. Describe events and their consequences, not just
  atmosphere.
- `status`: `"approved"`.

```json
[
  {"op": "replace", "path": "/chapters/2/actual_summary", "value": "Mara opens the letter and recognizes her mother's handwriting in the unsent reply folded inside. She hides both from her father."},
  {"op": "replace", "path": "/chapters/2/status", "value": "approved"}
]
```

(Chapter list indices are zero-based in the JSON path even though each chapter's own `index` field
is 1-based -- chapter `index: 3` is `/chapters/2`. Prefix the `replace` with a `{"op": "test",
"path": "/chapters/2/index", "value": 3}` op first if you want to guard against a stale index.)

Call `validate_story_bible` after writing.

## On rejection

Do not touch the chapter file itself -- rewriting prose is `writer-agent`'s job, not yours. Do not
change `status` or write an `actual_summary` for a rejected chapter. Instead, end your turn with
specific, actionable notes for `writer-agent`'s revision pass: name exactly what's wrong (a
continuity contradiction, a tone mismatch, a dropped beat) and, where useful, what a fix would
look like -- not just "needs work."

## When you're done

Your final message is either an approval (say so plainly, and confirm you wrote `actual_summary`
and `status=approved`) or a rejection with your specific notes for the revision pass. The
orchestrator reads this message directly to decide whether to move to the next chapter or
redelegate to `writer-agent`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing subagent-wiring test**

Append to `tests/test_subagents.py`:

```python
def test_chapter_reviewer_agent_is_registered_without_ask_human(
    settings: Settings, tmp_path: Path
) -> None:
    agent = _agent(settings, tmp_path, "chapter-reviewer-agent")
    assert "update_story_bible" in _tool_names(agent)
    assert "ask_human" not in _tool_names(agent)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_subagents.py::test_chapter_reviewer_agent_is_registered_without_ask_human -v`
Expected: FAIL with `StopIteration`

- [ ] **Step 7: Wire `chapter-reviewer-agent` into `build_subagents`**

In `src/psalm_saga/agents/subagents.py`, add a new `SubAgent` definition after `writer` and before `editor`:

```python
    chapter_reviewer: SubAgent = {
        "name": "chapter-reviewer-agent",
        "description": (
            "Runs once per chapter (and again per revision): reviews a just-drafted chapter "
            "(chapters/chapter_<NN>.md) against the outline, the previous chapter, and earlier "
            "chapters' actual_summary for prose quality, continuity, and fit against its "
            "planned_summary. Approves (recording actual_summary + status=approved) or returns "
            "specific revision notes for writer-agent."
        ),
        "system_prompt": load_prompt("chapter_reviewer"),
        "tools": [think, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }
```

And update the returned list:

```python
    return [
        extractor,
        brainstorm,
        originality_guard,
        chapter_planner,
        writer,
        chapter_reviewer,
        editor,
    ]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_subagents.py tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/psalm_saga/prompts/chapter_reviewer.md src/psalm_saga/agents/subagents.py tests/test_prompts.py tests/test_subagents.py
git commit -m "feat(agents): add chapter-reviewer-agent"
```

---

### Task 8: Rewrite `writer.md` for per-chapter drafting

**Files:**
- Modify: `src/psalm_saga/prompts/writer.md`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: nothing new in code; describes the `chapters/chapter_<NN>.md` file convention already implemented by Task 5's `assemble_draft` (`_chapter_filename`) and required by Task 10's rewritten `orchestrator.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompts.py`:

```python
def test_writer_prompt_drafts_one_chapter_not_the_full_story() -> None:
    text = load_prompt("writer")
    assert "write the full story" not in text
    assert "chapters/chapter_" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_writer_prompt_drafts_one_chapter_not_the_full_story -v`
Expected: FAIL (`"write the full story"` is still present in the current `writer.md`, and `"chapters/chapter_"` is absent)

- [ ] **Step 3: Rewrite `writer.md`**

Replace the full contents of `src/psalm_saga/prompts/writer.md` with:

```markdown
You are the writer subagent. You are delegated once per chapter (and again for any revision pass)
by the orchestrator, which tells you which chapter index to draft. Read `story_bible.json` (and,
in from_source mode, `divergence_plan` and the source text at `source_excerpt_path`) and write
that one chapter.

## What you're given

- The full chapter outline (`story_bible.json`'s `chapters` list) -- your chapter's own entry
  (`planned_summary`, `title`, `target_word_count`, `characters_present`) is what you're drafting
  toward; the rest of the list tells you where this chapter sits in the whole book.
- `actual_summary` for every earlier chapter except the immediately preceding one -- the running
  memory of what's actually happened so far.
- The full text of the immediately preceding chapter (`chapters/chapter_<NN-1>.md`), if this isn't
  chapter 1 -- for exact tone and continuity with how it ended.
- If this is a revision pass, `chapter-reviewer-agent`'s specific notes on what needs to change.

You are never given the complete book so far in full text -- only the immediately preceding
chapter plus running summaries for everything before that. Use the summaries for plot/character
continuity and the previous chapter's full text for how the prose itself should pick up (voice,
pacing, where a scene left off).

If any earlier chapter's `actual_summary` is missing (a gap in the record), fall back to that
chapter's `planned_summary` instead -- treat it as the best available account of what happened
there.

## Craft priorities, in order

1. Deliver your chapter's `planned_summary` -- honor its beats, but a specific, interesting
   deviation that still serves the story is better than a flat, literal read of the summary.
2. Honor the bible: every settled dimension should be legible in this chapter's prose. If a
   dimension is thin or unsettled, make a specific, interesting choice rather than writing around
   the gap generically -- but don't contradict anything the user settled, or anything established
   in an earlier chapter's `actual_summary`.
3. In from_source mode, honor `divergence_plan.per_dimension` precisely for this chapter's
   treatment of each PSALM dimension: `identical` (near-verbatim reuse of this dimension's
   content -- rare, mainly an extreme benchmarking test point), `close` (same core choices as the
   source, varied only in surface detail), `moderate` (recognizably related but with real,
   substantive changes), `loose` (only faint or structural resemblance), `divergent`
   (deliberately different -- don't let this dimension echo the source's choices). This precision
   is what makes the output usable for evaluation later; if unsure whether a choice reads as
   `close` vs `moderate`, err toward the more distinctive, less source-echoing option and let the
   editor's fidelity check catch it if you undershot.
4. In from_scratch mode, write something original and specific in its details -- concrete sensory
   choices, particular character quirks, an unusual but coherent world rule -- rather than generic
   genre prose. Avoid reusing any phrasing, names, or highly specific combinations of details from
   any real, identifiable work.
5. If this is a revision pass, address every point in `chapter-reviewer-agent`'s notes -- don't
   just polish around them.
6. Use `think` before drafting each major beat within the chapter to plan what it needs to
   accomplish, referencing the relevant bible fields and your chapter's `planned_summary`.
7. Target the chapter's `target_word_count` (within ~15%) -- it's a fixed per-chapter share of the
   book's total length, set once by `chapter-planner-agent` and not rebalanced, so don't pad or
   compress based on how other chapters have run.

Write the finished chapter to `chapters/chapter_<NN>.md` (zero-padded to two digits, e.g.
`chapters/chapter_03.md` for chapter 3) in the working directory -- plain prose, no bible
scaffolding, no chapter-heading line (the orchestrator's `assemble_draft` tool adds titles when it
concatenates every chapter into the final draft), no meta-commentary in the file itself. In your
final message to the orchestrator, summarize what you wrote and flag any bible fields or
`planned_summary` beats you had to interpret loosely.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/prompts/writer.md tests/test_prompts.py
git commit -m "docs(prompts): rewrite writer.md for per-chapter drafting"
```

---

### Task 9: Rewrite `brainstorm.md` title guidance

**Files:**
- Modify: `src/psalm_saga/prompts/brainstorm.md`
- Test: `tests/test_prompts.py`

**Interfaces:**
- No code interfaces; a prose-only change to how `brainstorm-agent` uses its existing `ask_human` tool.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompts.py`:

```python
def test_brainstorm_prompt_requires_title_proposal_not_optional() -> None:
    text = load_prompt("brainstorm")
    assert "fine to leave unsettled going into the writing stage" not in text
    assert "Titling the book" in text
    assert "Quokka Quest" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_brainstorm_prompt_requires_title_proposal_not_optional -v`
Expected: FAIL (the old "fine to leave unsettled" sentence is still present; "Titling the book" and "Quokka Quest" are absent)

- [ ] **Step 3: Rewrite the titling guidance**

In `src/psalm_saga/prompts/brainstorm.md`, replace this paragraph (in the "Conversation shape, not dimension order" section):

```markdown
This applies to `story_bible.json`'s other top-level fields too, not just the six PSALM dimensions
-- `title` in particular sits first in the file, right after `mode`, but that's a schema artifact,
not a conversation order. Always ask about the premise first (it's what everything else hangs off
of, and it's the one thing required before the story can be written). Titling, by contrast, is
optional -- it isn't required for writing at all -- and naturally comes *late*, once there's an
actual story to name; proposing a title before the premise exists is a guess with nothing to hang
on. Don't ask about it proactively until the rest of the bible has real shape, and even then treat
it as low-priority: happy to settle if the user offers one or asks, otherwise it's fine to leave
unsettled going into the writing stage.
```

with:

```markdown
This applies to `story_bible.json`'s other top-level fields too, not just the six PSALM dimensions
-- `title` in particular sits first in the file, right after `mode`, but that's a schema artifact,
not a conversation order. Always ask about the premise first (it's what everything else hangs off
of, and it's the one thing required before the story can be written). Titling comes *late* by the
same logic -- once there's an actual story to name, not before, since proposing a title before the
premise exists is a guess with nothing to hang on -- but titling is not optional: once premise,
characters, and plot have real shape, propose the book's title the same way you propose everything
else (see "Titling the book" below). Don't raise it before then.
```

Then, immediately after that section and before `## Ground rules`, insert a new section:

```markdown
## Titling the book

Once premise, characters, and plot have enough shape that a title could actually be grounded in
something specific (not necessarily fully settled -- but there should be a real premise, a
protagonist, and at least a sense of what's at stake), propose the title the same way you propose
everything else: lead with concrete options, via `ask_human` with `options` set, not an abstract
"what should we call it?"

Propose 2-4 real title candidates, each grounded in one specific image, line, object, or irony
already established in *this* story -- pulled from the premise, the climax, or a vivid character
or world detail, not from the genre or the protagonist's role in the abstract.

Bad titles -- avoid these shapes:
- Generic noun-phrase combos: "Quokka Quest", "The Last Lighthouse", "Shadow of the Storm" --
  interchangeable with a thousand other books, tells you nothing about *this* one.
- On-the-nose scene labels: "A Dark Underbelly", "The Final Confrontation" -- describes a beat
  instead of evoking it.

If the user declines to pick from your options (asks you to decide, or their answer doesn't
actually settle on one), settle on the strongest of your own candidates yourself and call
`update_story_bible` with `{"op": "replace", "path": "/title", "value": "..."}` -- do not leave
`title` empty going into the writing stage.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/prompts/brainstorm.md tests/test_prompts.py
git commit -m "docs(prompts): make brainstorm.md title proposal required-but-declinable"
```

---

### Task 10: Rewrite `orchestrator.md`'s writing loop

**Files:**
- Modify: `src/psalm_saga/prompts/orchestrator.md`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes (by name, in prose): `chapter-planner-agent` (Task 6), `chapter-reviewer-agent` (Task 7), `assemble_draft` (Task 5), `chapter_review_max_revisions` (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompts.py`:

```python
def test_orchestrator_prompt_documents_chapter_writing_loop() -> None:
    text = load_prompt("orchestrator")
    assert "draft the full story from the finalized bible" not in text
    assert "chapter-planner-agent" in text
    assert "chapter-reviewer-agent" in text
    assert "assemble_draft" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_orchestrator_prompt_documents_chapter_writing_loop -v`
Expected: FAIL (`orchestrator.md` still has the single-shot writer step, no mention of the new agents/tool)

- [ ] **Step 3: Rewrite the two sequences**

In `src/psalm_saga/prompts/orchestrator.md`, replace the entire `## mode = from_scratch` section with:

```markdown
## mode = from_scratch
Goal: produce a unique, detailed, compelling story that could not plausibly be mistaken for
anyone else's existing work, and does not rely on parody, pastiche, quotation, or scenes-a-faire
with respect to any identifiable existing work.

Sequence:
1. Delegate to `brainstorm-agent` to fill `story_bible.json` by conversing with the user, one
   question at a time, using the PSALM dimensions as your checklist. If the user supplied initial
   context, pass it along verbatim so the subagent doesn't re-ask what's already known.
2. Delegate to `originality-guard` to review the finished bible for the four exception categories
   and for resemblance to known works. If it reports unresolved findings, send the bible back to
   `brainstorm-agent` with the specific findings to address, then re-check. Do this for at most
   the configured revision budget.
3. Call `check_originality_gate`. If it returns BLOCKED, do not delegate to
   `chapter-planner-agent` -- report the open findings to the user and ask how they want to
   proceed (they may accept the risk explicitly, in which case say so plainly in your final
   message; you cannot silently override the block yourself). If it returns PROCEED (with or
   without a warn-mode note on open findings), continue to the next step.
4. Delegate to `chapter-planner-agent` once, to turn the finalized bible into a chapter outline
   (`story_bible.json`'s `chapters` list) sized to the bible's `length_tier`.
5. For each chapter, in order:
   a. Delegate to `writer-agent` to draft that chapter to `chapters/chapter_<NN>.md`.
   b. Delegate to `chapter-reviewer-agent` to review it.
   c. If it flags issues, delegate back to `writer-agent` with its specific notes, for at most the
      configured chapter-revision budget -- incrementing that chapter's `revision_count` via
      `update_story_bible` yourself each time you redelegate, so the budget check is a plain
      comparison against the bible's own state. If the budget is exhausted without approval,
      proceed with the last draft anyway and note it prominently in your final report.
   d. Add a fresh `write_todos` entry for each revision pass, the same way you would for the
      originality-guard loop above -- a chapter that needed two revisions should be visible in the
      live checklist, not silently absorbed into "writing chapter 7."
6. Once every chapter is `approved`, call `assemble_draft` to concatenate them into `draft.md`.
7. Delegate to `editor-agent` to review the draft for internal consistency with the bible and
   prose quality, and produce the final version.
8. Report back to the user: where the bible and story live, and a one-paragraph summary of what
   was generated plus any flagged originality concerns.
```

Then replace the entire `## mode = from_source` section's `Sequence:` block with:

```markdown
Sequence:
1. Delegate to `extractor-agent` to read the source text (path given to you) and populate
   `story_bible.json` from it. Then, unless `divergence_plan` was already complete when you
   started (see above), delegate to `brainstorm-agent` to negotiate one with the user: an
   intended similarity level per dimension. The subagent should propose a sensible default split
   if the user has no strong opinion, then confirm it explicitly. (In a non-interactive session,
   `brainstorm-agent` will decide on its own and note its assumptions instead of asking.)
2. Delegate to `chapter-planner-agent` once, to turn the finalized bible into a chapter outline
   sized to the bible's `length_tier`.
3. For each chapter, in order, run the same writer-agent / chapter-reviewer-agent loop (draft,
   review, revise up to the configured chapter-revision budget, fresh `write_todos` entry per
   revision) described in the from_scratch sequence above.
4. Once every chapter is `approved`, call `assemble_draft` to concatenate them into `draft.md`.
5. Delegate to `editor-agent` for a consistency and quality pass. The editor also assesses, per
   dimension, what similarity level the finished story actually achieved
   (`achieved_divergence`), and calls `check_fidelity_alignment`.
6. Read the `check_fidelity_alignment` result yourself. If it reports mismatches, note them
   prominently in your final report -- do not silently smooth them over, since they mean the
   story's actual similarity to the source doesn't match the label recorded in `divergence_plan`.
7. Report back to the user with the same summary shape as the from_scratch mode, plus the final
   divergence plan and any fidelity mismatches.
```

Finally, in `## General rules`, replace:

```markdown
- Never write final story prose yourself -- that's `writer-agent`'s job. Your job is sequencing,
  validation, and reporting.
```

with:

```markdown
- Never write final story prose yourself -- that's `writer-agent`'s job, one chapter at a time.
  Never assemble or edit `draft.md` by hand either -- that's what the `assemble_draft` tool is
  for, and it will refuse if any chapter isn't `approved` yet. Your job is sequencing, validation,
  and reporting.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/prompts/orchestrator.md tests/test_prompts.py
git commit -m "docs(prompts): rewrite orchestrator.md sequences for the chapter writing loop"
```

---

### Task 11: `--length` CLI option for `new`

**Files:**
- Modify: `src/psalm_saga/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `LengthTier` (Task 1), `init_session(..., length_tier=...)` (Task 4).
- Produces: `new(..., length: str = "long")`, validated into `LengthTier` and forwarded to `init_session`.

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_cli.py` (after the existing imports), the shared fakes and a helper this task and Task 12 will both use:

```python
from psalm_saga.dimensions import LengthTier  # type: ignore[import-untyped]


class _FakeState:
    tasks: tuple = ()
    values: dict = {}


class _FakeOrchestrator:
    def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return iter(())

    def get_state(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeState()


class _FakeCheckpointerCtx:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return object()

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False


class _FakeSqliteSaver:
    @staticmethod
    def from_conn_string(_path):  # type: ignore[no-untyped-def]
        return _FakeCheckpointerCtx()


def _stub_new_command_plumbing(monkeypatch: pytest.MonkeyPatch, tmp_path, captured: dict) -> None:  # type: ignore[no-untyped-def]
    def fake_init_session(settings, mode, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        session_dir = tmp_path / "sess"
        session_dir.mkdir(exist_ok=True)
        return session_dir

    monkeypatch.setattr(cli_module, "init_session", fake_init_session)
    monkeypatch.setattr(cli_module, "build_orchestrator", lambda *a, **k: _FakeOrchestrator())
    monkeypatch.setattr(cli_module, "SqliteSaver", _FakeSqliteSaver)
    monkeypatch.setenv("PSALM_SAGA_MODEL", "anthropic:claude-opus-4-8")
```

Append to `tests/test_cli.py`:

```python
def test_new_defaults_length_tier_to_long(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    _stub_new_command_plumbing(monkeypatch, tmp_path, captured)

    cli_module.new(sessions_root=tmp_path / "sessions")

    assert captured["length_tier"] is LengthTier.LONG


def test_new_honors_explicit_length_option(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    _stub_new_command_plumbing(monkeypatch, tmp_path, captured)

    cli_module.new(sessions_root=tmp_path / "sessions", length="medium")

    assert captured["length_tier"] is LengthTier.MEDIUM


def test_new_rejects_invalid_length_option(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    _stub_new_command_plumbing(monkeypatch, tmp_path, captured)

    with pytest.raises(typer.Exit):
        cli_module.new(sessions_root=tmp_path / "sessions", length="epic")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_new_defaults_length_tier_to_long tests/test_cli.py::test_new_honors_explicit_length_option tests/test_cli.py::test_new_rejects_invalid_length_option -v`
Expected: FAIL with `TypeError: new() got an unexpected keyword argument 'length'`

- [ ] **Step 3: Add `--length` to `new`**

In `src/psalm_saga/cli.py`, update the dimensions import line:

```python
from psalm_saga.dimensions import GenerationMode, DivergencePlan, DivergenceIntensity, PSALM_DIMENSIONS, LengthTier
```

In the `new(...)` signature, add a parameter after `guard_strictness`:

```python
        length: Annotated[
            str,
            typer.Option("--length", help="Book length tier: 'short', 'medium', or 'long'."),
        ] = "long",
```

In the body of `new(...)`, right after `settings = _build_settings(model, subagent_model, sessions_root, guard_strictness)`, insert:

```python
    try:
        length_tier = LengthTier(length)
    except ValueError:
        console.print(
            f"[red]Invalid --length value: \"{length}\" (expected short, medium, or long).[/red]"
        )
        raise typer.Exit(code=1)
```

And add `length_tier=length_tier,` to the `init_session(...)` call:

```python
    session_dir = init_session(
        settings,
        mode,
        source_path=source,
        initial_context=context,
        session_id=session_name,
        divergence_plan=divergence_plan,
        non_interactive=non_interactive,
        length_tier=length_tier,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/psalm_saga/cli.py tests/test_cli.py
git commit -m "feat(cli): add --length option to 'new' (default: long)"
```

---

### Task 12: `--length` CLI option for `batch`

**Files:**
- Modify: `src/psalm_saga/batch.py`
- Modify: `src/psalm_saga/cli.py`
- Test: `tests/test_batch.py` (new file), `tests/test_cli.py`

**Interfaces:**
- Consumes: `LengthTier` (Task 1), `init_session(..., length_tier=...)` (Task 4), the `_FakeOrchestrator`/`_FakeSqliteSaver` fakes from Task 11 (`tests/test_cli.py`).
- Produces: `run_dataset_item(..., length_tier: LengthTier = LengthTier.SHORT)`, `run_batch(..., length_tier: LengthTier = LengthTier.SHORT)`, `batch(..., length: str = "short")` CLI option.

- [ ] **Step 1: Write the failing `batch.py`-level tests**

Create `tests/test_batch.py`:

```python
from pathlib import Path

import pytest

import psalm_saga.batch as batch_module
from psalm_saga.config import Settings  # type: ignore[import-untyped]
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    StoryBible,
)


class _FakeOrchestrator:
    def invoke(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {}


class _FakeCheckpointerCtx:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return object()

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False


class _FakeSqliteSaver:
    @staticmethod
    def from_conn_string(_path):  # type: ignore[no-untyped-def]
        return _FakeCheckpointerCtx()


def test_run_dataset_item_forwards_length_tier_to_init_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    plan = DivergencePlan.uniform(DivergenceIntensity.CLOSE)

    def fake_init_session(settings, mode, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        session_dir = tmp_path / "item-session"
        session_dir.mkdir(exist_ok=True)
        bible = StoryBible(mode=GenerationMode.FROM_SOURCE, divergence_plan=plan)
        (session_dir / "story_bible.json").write_text(bible.model_dump_json())
        return session_dir

    monkeypatch.setattr(batch_module, "init_session", fake_init_session)
    monkeypatch.setattr(batch_module, "build_orchestrator", lambda *a, **k: _FakeOrchestrator())
    monkeypatch.setattr(batch_module, "SqliteSaver", _FakeSqliteSaver)

    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("Once upon a time...")

    item = batch_module.run_dataset_item(
        settings, source, "baseline_all_close", plan, length_tier=LengthTier.MEDIUM
    )

    assert captured["length_tier"] is LengthTier.MEDIUM
    assert item.status == "ok"


def test_run_batch_forwards_length_tier_to_every_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "a.txt").write_text("A story.")

    captured: list[object] = []

    def fake_run_dataset_item(  # type: ignore[no-untyped-def]
        settings, source_path, variant_name, plan, *, context="", overwrite=False,
        length_tier=LengthTier.SHORT,
    ):
        captured.append(length_tier)
        return object()

    monkeypatch.setattr(batch_module, "run_dataset_item", fake_run_dataset_item)

    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    batch_module.run_batch(
        settings,
        sources_dir,
        dimensions=["plot"],
        include_baselines=False,
        length_tier=LengthTier.MEDIUM,
    )

    assert captured
    assert all(lt is LengthTier.MEDIUM for lt in captured)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch.py -v`
Expected: FAIL with `TypeError: run_dataset_item() got an unexpected keyword argument 'length_tier'`

- [ ] **Step 3: Thread `length_tier` through `batch.py`**

In `src/psalm_saga/batch.py`, update the dimensions import line:

```python
from psalm_saga.dimensions import PSALM_DIMENSIONS, DivergenceIntensity, DivergencePlan, evaluate_fidelity, \
    GenerationMode, IsolationStrategy, LengthTier, build_isolation_matrix
```

Add a parameter to `run_dataset_item`, after `overwrite: bool = False`:

```python
        length_tier: LengthTier = LengthTier.SHORT,
```

Pass it through to `init_session` inside `run_dataset_item`:

```python
        session_dir = init_session(
            settings,
            GenerationMode.FROM_SOURCE,
            source_path=source_path,
            initial_context=context,
            session_id=session_id,
            divergence_plan=plan,
            non_interactive=True,
            length_tier=length_tier,
        )
```

Add a parameter to `run_batch`, after `overwrite: bool = False`:

```python
        length_tier: LengthTier = LengthTier.SHORT,
```

Pass it through to each `run_dataset_item(...)` call inside `run_batch`:

```python
            item = run_dataset_item(
                settings,
                source_path,
                variant_name,
                plan,
                context=context,
                overwrite=overwrite,
                length_tier=length_tier,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing CLI-level tests**

Append to `tests/test_cli.py`:

```python
def test_batch_defaults_length_tier_to_short(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_run_batch(settings, sources_dir, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli_module, "run_batch", fake_run_batch)
    monkeypatch.setenv("PSALM_SAGA_MODEL", "anthropic:claude-opus-4-8")

    cli_module.batch(
        tmp_path, sessions_root=tmp_path / "sessions", output=tmp_path / "manifest.json"
    )

    assert captured["length_tier"] is LengthTier.SHORT


def test_batch_honors_explicit_length_option(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_run_batch(settings, sources_dir, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli_module, "run_batch", fake_run_batch)
    monkeypatch.setenv("PSALM_SAGA_MODEL", "anthropic:claude-opus-4-8")

    cli_module.batch(
        tmp_path,
        sessions_root=tmp_path / "sessions",
        output=tmp_path / "manifest.json",
        length="long",
    )

    assert captured["length_tier"] is LengthTier.LONG


def test_batch_rejects_invalid_length_option(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PSALM_SAGA_MODEL", "anthropic:claude-opus-4-8")

    with pytest.raises(typer.Exit):
        cli_module.batch(tmp_path, sessions_root=tmp_path / "sessions", length="epic")
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_batch_defaults_length_tier_to_short tests/test_cli.py::test_batch_honors_explicit_length_option tests/test_cli.py::test_batch_rejects_invalid_length_option -v`
Expected: FAIL with `TypeError: batch() got an unexpected keyword argument 'length'`

- [ ] **Step 7: Add `--length` to the `batch` CLI command**

In `src/psalm_saga/cli.py`, add a parameter to `batch(...)`, after `overwrite`:

```python
        length: Annotated[
            str,
            typer.Option("--length", help="Book length tier for every generated item: 'short', 'medium', or 'long'."),
        ] = "short",
```

In the body of `batch(...)`, right after `settings = _build_settings(model, subagent_model, sessions_root, None)`, insert:

```python
    try:
        length_tier = LengthTier(length)
    except ValueError:
        console.print(
            f"[red]Invalid --length value: \"{length}\" (expected short, medium, or long).[/red]"
        )
        raise typer.Exit(code=1)
```

And add `length_tier=length_tier,` to the `run_batch(...)` call:

```python
    items = run_batch(
        settings,
        sources_dir,
        dimensions=dim_list,
        strategy=strategy,  # type: ignore[arg-type]
        include_baselines=include_baselines,
        near=DivergenceIntensity(near),
        far=DivergenceIntensity(far),
        context=context,
        overwrite=overwrite,
        progress_callback=_on_progress,
        length_tier=length_tier,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py tests/test_batch.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (every test in `tests/`, including all tests from Tasks 1-11)

- [ ] **Step 10: Commit**

```bash
git add src/psalm_saga/batch.py src/psalm_saga/cli.py tests/test_batch.py tests/test_cli.py
git commit -m "feat(cli,batch): add --length option to 'batch' (default: short), thread through run_batch/run_dataset_item"
```
