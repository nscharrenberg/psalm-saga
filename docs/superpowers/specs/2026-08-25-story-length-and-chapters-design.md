# Story length and chapter count configuration

Status: approved design, not yet implemented.

## Motivation

Story length today is decided entirely inside the conversation:
`story-brainstorming` Step 1 just says "ask what the person is trying to
write and why: audience, length, genre" — there is no predefined
vocabulary for length (drabble vs. novella vs. novel), no way to hand a
specific word target or range in from the CLI, and no concept of chapter
count at all beyond whatever `writing-story-plans` improvises per story.
`psalm-saga-batch` in particular has no way to request "give me ten flash
fiction pieces" or "give me one novella" — every batch run today produces
whatever length the model happens to land on.

This design adds a `--length` and `--chapters` flag to both `psalm-saga`
and `psalm-saga-batch`, backed by a small shared parsing module, so a
target length (a predefined category or a custom word count/range) and
optionally a target chapter count (explicit or auto-estimated) can be
locked in before brainstorming starts, while leaving the actual creative
judgment — how to pace a novella's chapters, whether a "12,000-word
custom" target reads as flash fiction or a short novelette — inside the
skills, where the rest of this system's creative decisions already live.

## Goals

- `--length` on both CLIs: a predefined category keyword, or a custom
  word count/range, defaulting to `short-story` when omitted.
- `--chapters` on both CLIs: an explicit chapter count/range, or `auto`
  (the default) — auto-estimation is a word-count-driven heuristic
  documented in a shared skill reference, not a hardcoded formula.
- For `psalm-saga` (interactive), the flag locks the length dimension for
  a **fresh** session the same way a signed-off spec dimension is locked
  — `story-brainstorming` states it back rather than asking. The
  underlying conversation can still revise it later the same way any
  other spec dimension can be revised.
- For `psalm-saga-batch`, the flag applies uniformly to every story in
  the run (one fixed target, not a per-story draw) and rides along in the
  existing per-story instruction message, next to `Mode`/`Combine`/
  `Inputs`.
- Default behavior (`--length` unspecified everywhere) resolves to
  `short-story`, matching today's de facto behavior of "whatever length
  the model happens to produce," now made explicit.

## Non-goals

- Changing anything about *how* chapters get drafted or reviewed
  (`drafting-chapters`, `reviewing-story-dimensions` are unaffected — they
  execute whatever chapter list `writing-story-plans` decided on).
- Letting a single `psalm-saga-batch` run mix multiple length targets
  across its stories (out of scope for this design; run the CLI multiple
  times with different `--length` values for a varied batch).
- A hard, code-enforced word-count check against the finished draft —
  length remains a target the model works toward via the same
  spec/plan/review pipeline as every other dimension, not a post-hoc
  validator.

## Length taxonomy

A non-overlapping category ladder, `psalm_saga/story_length.py`:

| Category slug | Label | Range (words) |
|---|---|---|
| `drabble` | Drabble | exactly 100 |
| `flash-fiction` | Flash Fiction | 1–999 |
| `short-story` | Short Story | 1,000–7,499 |
| `novelette` | Novelette | 7,500–17,499 |
| `novella` | Novella | 17,500–39,999 |
| `novel` | Novel | 40,000–149,999 |
| `epic` | Epic / Doorstopper | 150,000+ |

Boundaries are drawn so each word count belongs to exactly one category
(the boundary word goes to the higher category) — resolving the overlap
between the originally-proposed "long short story" and "novelette"
brackets by dropping "long short story" as a separate selectable
category; its range is absorbed into `novelette`, matching standard
SFWA-style usage. Category slugs accept a couple of ergonomic aliases
(`flash` → `flash-fiction`, `short` → `short-story`, `doorstopper` →
`epic`).

## CLI surface

New flags, identical on both `psalm-saga` and `psalm-saga-batch`:

```
--length {drabble,flash-fiction,short-story,novelette,novella,novel,epic}
--length N              # exact custom word target, e.g. --length 12000
--length N-M            # custom word range, e.g. --length 12000-18000
--chapters auto          # default; word-count-driven estimate
--chapters N             # exact chapter count
--chapters N-M           # chapter count range
```

Both flags are parsed via `story_length.parse_length` / `parse_chapters`
as the argparse `type=` callable, so an invalid value (non-positive,
`min > max`, unrecognized category) fails CLI argument parsing directly
with a clear message, before any agent turn runs.

`story_length.py` exposes:

- `LengthSpec` — resolved category (if any), `min_words`, `max_words`
  (`None` = open-ended, only `epic` uses this), and a display label. A
  custom number/range also carries which category bucket it falls into
  (by its midpoint, or "spans X–Y" if the range crosses more than one
  bucket) purely as a hint for the length-and-chapters reference's
  chapter guidance — it does not restrict what the user can type.
- `ChapterSpec` — `mode: "auto" | "exact" | "range"` plus the resolved
  count/range.
- `parse_length(raw: str | None) -> LengthSpec`, `raw=None` → the
  `short-story` default.
- `parse_chapters(raw: str | None) -> ChapterSpec`, `raw=None` or
  `"auto"` → auto mode.
- `format_length_directive(length: LengthSpec, chapters: ChapterSpec) ->
  str` — the one short instruction block threaded into the agent, e.g.:

  > Story length directive: novella, target 17,500–40,000 words. Chapter
  > count: auto — decide per the length-and-chapters guidance based on
  > the resolved word target.

  or, for a fully explicit case:

  > Story length directive: custom, target 12,000–18,000 words (novelette
  > range). Chapter count: 4 (explicit).

## Threading the directive into each entry point

- **`batch_cli.py`**: `--length`/`--chapters` are parsed once in
  `_parse_args` (uniform for the whole run, per the Goals above). The
  formatted directive is appended into `_build_story_instruction`'s
  per-story message, alongside `Mode`/`Combine`/`Inputs` — `batch-story-
  generation`'s Autonomous Mode treats it as locked input, the same way
  a template-locked dimension is already treated.
- **`cli.py`**: `--length`/`--chapters` are parsed once at startup. The
  directive is passed as extra `system_prompt` text into `build_agent(...)`
  **only when starting a brand-new session** — `_run_one_session` already
  distinguishes fresh vs. resumed via `is_resuming`, so this reuses that
  check. `compose_system_prompt` places the caller's `application_prompt`
  before the bootstrap, so the directive is present from the model's very
  first turn, ahead of `using-psalm-saga`. On a resumed session, the flag
  is not injected and is silently ignored — the spec dimension it would
  have locked is either already decided or already in the middle of being
  decided conversationally, and re-injecting it risks contradicting
  something the human partner already chose.

## Skill changes

**New reference file** —
`psalm_saga/skills/story-brainstorming/references/length-and-chapters.md`:
the taxonomy table above, plus the chapter-count heuristic as prose
guidance (not a formula the code enforces):

- Drabble, flash fiction, short story, and novelette: no formal chapters
  — continuous prose, optionally broken by a few scene dividers, never
  numbered/titled chapters.
- Novella: a pacing judgment call. Often no chapters; if chaptered, it's
  usually a handful (roughly 3–10).
- Novel: the first category where chapters are a real convention, but
  still entirely the author's choice — anywhere from a handful of long
  chapters to dozens of short ones. Where an author does chapter it,
  ~1,500–5,000 words per chapter is a common stylistic norm, explicitly
  called out as a norm to consider, not a rule to apply mechanically.
- Epic/doorstopper: essentially always chaptered at this length; use the
  word target and the novel guidance above as the starting point.

This file is the single source of truth for the heuristic; both skills
below read it rather than duplicating the prose.

**`story-brainstorming/SKILL.md`, Step 1 (Premise):**
- If a length directive is present (injected `system_prompt` text for a
  fresh interactive session, or the batch per-story message), treat the
  category/word target as already decided: state it back to the human
  partner rather than asking, then continue with the surrounding
  audience/genre/feel questions as before.
- If no directive is present, ask about length as today; if the person
  has no real preference, default to short story.
- Read `references/length-and-chapters.md` the first time length comes up
  in a session, following the same read-the-reference-once convention the
  other dimension reference files already use.
- **Autonomous Mode**: one added line — a batch per-story message may
  carry a length directive; treat it as locked, the same as a
  template-locked dimension, never re-decide it.

**`writing-story-plans/SKILL.md`, Step 2 (whole-story plan):**
- Before writing the chapter list, check for a chapter-count directive.
  If explicit (`--chapters`), use it as given. If `auto` (the default),
  read `references/length-and-chapters.md` (via
  `story-brainstorming`'s copy — not duplicated here) and decide,
  recording the reasoning inline in the plan, e.g. "Chapter count: 6 —
  auto, ~4,000 words/chapter target for this ~25k-word novel."
- Short forms (drabble through novelette) get a one-line note instead of
  a chapter list entry: "No formal chapters — continuous prose, N scene
  breaks," consistent with the reference file.
- **Autonomous Mode**: same locked-directive line as `story-brainstorming`'s.

**`batch-story-generation/SKILL.md`:** one added line under "What you'll
receive" noting the per-story instruction message may include a length
directive line, treated as locked input exactly like the existing
`Mode`/`Combine`/`Inputs` fields.

`drafting-chapters`, `reviewing-story-dimensions`, and `using-psalm-saga`
need no changes — none of them decide length or chapter count; they
execute or check whatever `writing-story-plans` already committed to.

## Testing

- Unit tests for `story_length.py`: category parsing (including aliases),
  custom number/range parsing, boundary values across every category,
  bucket-hinting for a custom value/range, and error cases (non-positive,
  `min > max`, unrecognized category).
- `batch_cli` tests confirming the formatted directive lands in the
  per-story instruction message when `--length`/`--chapters` are passed,
  and that the default (`short-story`, `auto`) is used when they're
  omitted.
- `cli` tests confirming the directive is passed into `build_agent`'s
  `system_prompt` on a fresh session and omitted on a resumed one.
- The actual creative outcome (does the model really hit the target
  length, does "auto" chapter count look reasonable) isn't unit-testable
  — it belongs in `tests/evals/` alongside the existing harness, the same
  way batch story generation's own autonomous-decision behavior does.

## Open questions for implementation time

- Exact wording of the locked-directive restatement in
  `story-brainstorming` Step 1 and the auto-chapter-count reasoning note
  in `writing-story-plans` Step 2 — drafted during implementation,
  reviewed the same way any skill edit is.
- Whether the custom-length bucket hint (used only for chapter-guidance
  purposes) needs any refinement once real runs are observed using a
  custom range that spans multiple categories.
