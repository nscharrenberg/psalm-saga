# Chapter-by-chapter generation with length tiers

## Problem

`writer-agent` currently drafts the entire story in a single subagent turn, writing one
`draft.md` in one pass (`prompts/writer.md`). A representative session
(`psalm-saga-sessions/20260805-111947-a6d543/`) produced a 532-word "story" with five
one-paragraph "chapters" plus an epilogue — chapter headers invented on the spot, with no
outline, no per-chapter review, and no mechanism for the story to grow beyond whatever fits in
one writer turn. Nothing resembles how a book actually gets written: planned, drafted section by
section, and reviewed for internal fit as it goes.

The same session shows the second symptom: `story_bible.json`'s `title` field was left `""`
because `brainstorm.md` explicitly treats titling as optional ("fine to leave unsettled going
into the writing stage"). Nothing downstream ever proposes a real one — `writer-agent` just
improvises a title cold while drafting, with no guidance on what makes a title good, producing
generic results ("Quokka Quest" for a story about a Quokka cult).

This spec introduces **length tiers** (short / medium / long), a **chapter-by-chapter writing
loop** with a per-chapter planner and reviewer, and **required, guided title proposals** (book
title and per-chapter titles) to replace both the one-shot writer and the optional, unguided
title field.

## Non-goals

- **No change to `extractor-agent`, `originality-guard`, the divergence-plan negotiation, or the
  originality gate.** This spec is scoped to what happens *after* the bible is finalized and
  *before* the final editor pass — i.e., it replaces the single `writer-agent` delegation with a
  planning step plus a per-chapter loop, and extends `editor-agent`'s existing whole-book pass
  only enough to read the newly-assembled `draft.md`. The originality guard continues to review
  the *bible* (unchanged); `editor-agent` continues to be the from_scratch-mode final skim for
  uncredited near-copies (unchanged) and the from_source-mode fidelity self-check (unchanged —
  still a whole-book judgment, not per-chapter, since divergence intensity is assessed against
  the complete finished story).
- **No per-chapter user interaction.** The book title goes through the user (via
  `brainstorm-agent`, extending its existing `ask_human` pattern); chapter titles and chapter
  content do not — `chapter-planner-agent` and `chapter-reviewer-agent` are agent-only steps, the
  same way `originality-guard` already is.
- **No `batch` manifest schema change.** `batch.py`/`dataset_utils.py` key off
  `final_story.md` existing to decide whether an item is already done (`dataset_utils.py:32`);
  that contract is untouched — `final_story.md` still means "this item is finished," regardless
  of how many chapters it took to get there.
- **No mid-book length adjustment.** The chosen tier fixes chapter count for the whole session;
  there's no mechanism to shrink or grow the outline once `chapter-planner-agent` has run.

## Design

### Length tiers

```python
class LengthTier(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"

@dataclass(frozen=True)
class LengthTierSpec:
    min_chapters: int
    max_chapters: int
    target_total_words: int

LENGTH_TIER_SPECS: dict[LengthTier, LengthTierSpec] = {
    LengthTier.SHORT:  LengthTierSpec(min_chapters=1,  max_chapters=1,  target_total_words=2_000),
    LengthTier.MEDIUM: LengthTierSpec(min_chapters=6,  max_chapters=10, target_total_words=20_000),
    LengthTier.LONG:   LengthTierSpec(min_chapters=25, max_chapters=35, target_total_words=90_000),
}
```

Lives in `dimensions.py` alongside the other dependency-light constants (`PSALM_DIMENSIONS`,
`DIVERGENCE_ORDER`), so `chapter-planner-agent`'s prompt and `build_isolation_matrix`-style
pure logic can both reference it without pulling in `deepagents`/`langgraph`.

`StoryBible` gains:

```python
length_tier: LengthTier = LengthTier.LONG
chapters: list[Chapter] = Field(default_factory=list)
```

`length_tier` is operator-supplied configuration, not something an agent negotiates — set once
in `init_session` (mirroring how `divergence_plan`/`source_excerpt_path` are set today, not
through `update_story_bible`) from a new `--length` CLI option, and immutable for the session the
same way `mode` is (no patch touches it after `init_session` writes the initial bible).

### CLI

`--length {short,medium,long}` added to both `new` and `batch`:
- `new` defaults to `long`.
- `batch` defaults to `short`, applied uniformly across every generated item in a matrix run —
  keeping the benchmarking pipeline's current fast/cheap behavior as the default, while letting a
  specific dataset opt into longer items (`--length medium`/`--length long`) when it needs them.
  `isolation-matrix` (the preview-only command) is unaffected — it only prints divergence plans,
  never generates prose.

`SessionConfig` (`session.py`) gains a `length_tier: str` field, recorded and reloaded the same
way `originality_guard_strictness` is, so `saga resume` doesn't need `--length` repeated.

### Schema: `Chapter`

```python
class ChapterStatus(StrEnum):
    PLANNED = "planned"
    DRAFTED = "drafted"
    APPROVED = "approved"

class Chapter(BaseModel):
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

`target_word_count` per chapter is `target_total_words // chapter_count` from the tier spec,
set once by `chapter-planner-agent` and not rebalanced afterward (a chapter running short or long
doesn't reshuffle neighboring targets — `writer.md`'s existing "within ~15%" tolerance applies
per chapter the way it applies to `target_length_words` today).

### New subagents

**`chapter-planner-agent`** — runs once, after the bible is finalized (after the originality
gate in from_scratch mode; after divergence-plan negotiation, or immediately if pre-set, in
from_source mode) and before any prose is written.

- Reads the finalized `story_bible.json` and `length_tier`.
- If `title` is still unset (the user declined to pick one during brainstorming — see below),
  picks the strongest of its own candidates rather than leaving it blank.
- Writes `chapters: list[Chapter]` via `update_story_bible`: one entry per chapter (count within
  the tier's `min_chapters`/`max_chapters`, chosen to fit the plot's actual turning points rather
  than mechanically hitting the max), each with `title`, `planned_summary`, and
  `target_word_count`, `status=planned`.
- Tools: `think`, `update_story_bible`, `validate_story_bible`. No `ask_human` — this is a
  planning pass, not a conversation.
- Title-quality guidance (both here and in `brainstorm.md`, see below) is written the same way
  `brainstorm.md` teaches dimension-translation: concrete good/bad examples, not an abstract
  "avoid generic titles" instruction. Bad: generic noun-phrase combos ("Quokka Quest"),
  on-the-nose scene labels ("A Dark Underbelly"). Good: grounded in a specific image, line,
  object, or irony that's already in *this* bible (e.g., a title built from a concrete detail in
  `premise`/`plot.climax` rather than the genre or protagonist's role in the abstract).

**`chapter-reviewer-agent`** — runs once per chapter (and again per revision), inside the
per-chapter loop below.

- Reads: the full chapter outline (all `chapters` entries), the chapter just drafted
  (`chapters/chapter_<NN>.md`), the previous chapter in full (`chapters/chapter_<NN-1>.md`, for
  immediate tone/continuity), and every earlier chapter's `actual_summary` (not their full text).
- Checks: prose quality against `writing_style`/`narrative_voice`, continuity with the previous
  chapter's ending and the running summaries (no unacknowledged contradictions, no silently
  dropped threads), and fit against `planned_summary`'s beats (deviation is fine if it's a
  deliberate, coherent choice — flag it only if it reads as drift, not intent).
- On approval: writes `actual_summary` and sets `status=approved` via `update_story_bible`.
- On rejection: does not touch the chapter file itself (that's `writer-agent`'s job) — returns
  specific, actionable notes for `writer-agent`'s revision pass.
- Tools: `think`, `update_story_bible`, `validate_story_bible`.

Both are added to `build_subagents` (`agents/subagents.py`) alongside the existing five, with new
prompt files `prompts/chapter_planner.md` and `prompts/chapter_reviewer.md`.

### Orchestration: the writing loop

Replaces `orchestrator.md`'s single "delegate to writer-agent" step (step 4 in from_scratch mode,
step 2 in from_source mode) with:

1. Delegate to `chapter-planner-agent` once.
2. For each chapter, in order:
   a. Delegate to `writer-agent` to draft `chapters/chapter_<NN>.md` (a new, smaller file per
      chapter rather than one growing `draft.md` — keeps each subagent's read/write footprint
      bounded instead of re-touching an ever-larger file). `writer-agent`'s inputs for chapter N:
      the full outline, `actual_summary` for chapters `1..N-2`, the full text of chapter `N-1`,
      and the relevant bible fields — never the full text of everything written so far, so
      per-chapter cost stays roughly flat instead of growing with book length.
   b. Delegate to `chapter-reviewer-agent`.
   c. If it flags issues, delegate back to `writer-agent` with the specific notes, bounded by a
      new `chapter_review_max_revisions` setting (default `2`, mirroring
      `originality_guard_max_revisions`'s shape). The orchestrator increments that chapter's
      `revision_count` via `update_story_bible` each time it redelegates (the same way it, not a
      subagent, owns sequencing) so the budget check is a plain comparison against the bible's
      own state, not something the orchestrator has to count itself across turns. If the budget
      is exhausted without approval, proceed with the last draft anyway and note it in the final
      report — same "warn, don't hang the whole run" behavior the originality guard's revision
      budget already has.
   d. Add a fresh `write_todos` entry for each revision pass, per the orchestrator's existing rule
      for repeated steps (originality-guard loop, gate BLOCKED) — a chapter that needed two
      revisions should be visible in the live checklist, not silently absorbed into "writing
      chapter 7."
3. Once every chapter is `approved`, call a new deterministic `assemble_draft` tool — added to
   the orchestrator's own tool list in `agents/orchestrator.py` alongside
   `check_originality_gate`/`check_fidelity_alignment` (not given to any subagent; the
   orchestrator calls it directly, the same "sequencing and validation is my job" role it already
   plays) — that concatenates `chapters/*.md` in order, prefixed by the book title and each
   chapter's title, into `draft.md`. This keeps `draft.md`'s existing role intact:
   `editor-agent` reads it exactly as it does today, and `dataset_utils.py`'s
   `final_story.md`-exists check downstream is unaffected since `editor-agent` still produces
   `final_story.md` from it the same way.
4. Delegate to `editor-agent` for the existing whole-book pass — unchanged from today.

The short tier (one chapter) still goes through this full sequence rather than a special-cased
shortcut: `chapter-planner-agent` produces a single-entry outline, `chapter-reviewer-agent`
reviews that one chapter, and `editor-agent`'s final pass is unchanged. One code path for all
three tiers, only the outline length differs.

`orchestrator.md` gets new todo-list step descriptions for chapter planning and "writing chapter
N of M" per the existing `write_todos`-first-action convention; `writer.md` is rewritten from
"write the full story to draft.md" to "write one chapter, given its outline entry and the
continuity context described above, to `chapters/chapter_<NN>.md`."

### Title handling

`brainstorm.md`'s current guidance — "happy to settle if the user offers one or asks, otherwise
fine to leave unsettled" — is replaced with a required (but still user-declinable) step: once
premise, characters, and plot have real shape (the same "titling comes late" placement already
described in the file), `brainstorm-agent` proposes 2-4 concrete, specific title options via
`ask_human` (same pattern as every other dimension: lead with a real proposal, not an abstract
question), grounded in what's actually been established. If the user explicitly declines to pick
(including non-interactive sessions, via the existing `NO_HUMAN_AVAILABLE` path), `brainstorm-agent`
settles on the strongest of its own proposals rather than leaving `title` empty — matching how it
already handles `NO_HUMAN_AVAILABLE` for every other field.

If `title` somehow still reaches `chapter-planner-agent` unset (e.g. a pre-seeded from_source
bible with `divergence_plan` supplied but no title), `chapter-planner-agent` is the fallback that
sets it, per the previous section — so writing never begins without a real title, but the user
gets first say whenever there's a user in the loop at all.

### Files

```
psalm-saga-sessions/<session-id>/
    session_config.json
    psalm_dimensions_reference.md
    story_bible.json
    source.txt              # from_source mode only
    chapters/
        chapter_01.md        # one file per chapter, written by writer-agent
        chapter_02.md
        ...
    draft.md                 # assembled by the new assemble_draft tool once all chapters approved
    final_story.md           # written by editor-agent, unchanged
    checkpoints.sqlite
```

## Error handling

- **`chapter-planner-agent` produces an out-of-range chapter count**: `update_story_bible`'s
  existing schema validation doesn't constrain chapter count (that's a soft planning guideline,
  not a hard schema rule) — the orchestrator's existing "call `validate_story_bible`, use your own
  judgment if a subagent's updates aren't converging" rule covers it: `validate_story_bible`
  reports the bible is schema-valid, and it's on the orchestrator's `think`-before-delegating step
  to notice a wildly out-of-tier chapter count and re-delegate with a correction, the same way it
  already handles any other under-converging subagent output.
- **`chapter-reviewer-agent` keeps rejecting past the revision budget**: proceed with the last
  draft, flagged in the final report (see loop step 2c) — never blocks the run indefinitely.
- **`assemble_draft` runs with a chapter still `planned`/`drafted` (not `approved`)**: refuses and
  returns which chapter(s) are incomplete, the same "report, don't guess" shape as
  `check_originality_gate`/`check_fidelity_alignment` — this should be unreachable given the loop
  above but guards against the orchestrator skipping ahead.
- **Stale/missing `actual_summary` for an early chapter** (e.g. `chapter-reviewer-agent` approved
  a chapter without recording one): `writer-agent` drafting a later chapter falls back to that
  chapter's `planned_summary` instead — degraded continuity fidelity for that one chapter, not a
  blocked run.

## Testing

No live model calls, consistent with the rest of the suite:

- `dimensions.py`: `LENGTH_TIER_SPECS` values, `Chapter`/`ChapterStatus` schema round-trips,
  `StoryBible.chapters` default-empty and patch-compatible via the existing
  `update_story_bible` test patterns.
- `tools/bible.py`-equivalent new tool tests for `assemble_draft`: concatenates approved chapters
  in order with title prefixes; refuses (with the specific incomplete chapters named) when any
  chapter isn't `approved`.
- `session.py`: `init_session` writes `length_tier` into both the bible and `SessionConfig`;
  `load_session_config` round-trips it.
- `cli.py`: `--length` parsed/validated for both `new` and `batch`, default values per command.
- No new coverage needed for `dataset_utils.py`'s reuse/regenerate logic — it's unchanged, keyed
  on `final_story.md` as before.

## Known tradeoffs

- **Cost and wall-clock time scale with chapter count.** A long-tier session is on the order of
  25-35 write+review round trips (more with revisions) versus today's single writer call — this
  is the explicit point of the feature, but it means a `long` session is substantially slower and
  more expensive than today's one-shot generation. `batch`'s `short` default keeps existing
  dataset-generation runs unaffected unless a run explicitly opts into a longer tier.
- **`chapter-reviewer-agent`'s continuity check is bounded, not exhaustive.** Reading only the
  immediately preceding chapter in full plus running summaries (not the complete book) trades
  some deep-continuity precision for flat per-chapter cost — a subtle callback to chapter 3
  planted in chapter 25 is only as reliable as chapter 3's `actual_summary` captured it. This
  mirrors the same kind of self-report reliance `achieved_divergence` already has (see
  `docs/design.md`'s "Known limitations").
