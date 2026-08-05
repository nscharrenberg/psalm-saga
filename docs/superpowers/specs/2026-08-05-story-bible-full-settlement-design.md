# Story bible full settlement

## Problem

`psalm-saga new` hands the bible off to `writer-agent` far too early. Three independent gaps produce this:

1. **The readiness gate is much weaker than "settled" implies.** `StoryBible.is_ready_for_writing()` (`src/psalm_saga/dimensions.py:397`) — the only function deciding whether `writer-agent` can start — checks that just four fields are *non-empty*: `premise`, at least one character, `plot.structure`, `plot.inciting_incident`. It never reads the `DimensionField.settled` flag, and `writing_style`, `narrative_voice`, `world_building`, and `scenes` aren't checked at all, even for presence.
2. **`brainstorm.md`'s turn-budget guidance reinforces early stopping.** It explicitly tells the subagent that once turns run low, it's fine to settle only those same four minimal fields and leave everything else unsettled (`prompts/brainstorm.md:124-127`). `writer.md` then tells the writer to paper over any "thin or unsettled" dimension with its own invented choice.
3. **`--context` has no extraction step.** The free-text seed is forwarded verbatim into `brainstorm-agent`'s task ("pass it along verbatim so the subagent doesn't re-ask what's already known" — `orchestrator.md:31`), but nothing instructs it to mine that text for already-decided facts before asking questions. `from_source` mode has a dedicated `extractor-agent` for this; `from_scratch` mode has no equivalent.

Also relevant: the `settled` bool currently exists only on `WritingStyle`/`NarrativeVoice`/`WorldBuilding` fields — `Character`, `PlotArchitecture`, and `Scene` have no per-field settled tracking at all, so "settled" doesn't currently cover the whole bible even where it's used.

## Goals

- `writer-agent` never starts until every gated field in the bible is genuinely settled (or the user has explicitly chosen to proceed anyway).
- Minimize the number of questions asked, by shaping each proposal to resolve multiple related fields at once — not by bundling unrelated questions into one call.
- `--context` seed text is mined for stated facts and confidently interpreted for what it implies, before any question is asked.
- No deadlock: a bounded, user-controlled path exists for when settlement is taking too long.

## Scope

Applies to both `from_scratch` and `from_source` modes. In `from_source` mode this closes an existing gap: `extractor.md` already tells subagents that ambiguous/silent parts are left for "the brainstorm subagent to resolve... later," but `orchestrator.md`'s sequence never actually sends `brainstorm-agent` to do that — only to negotiate `divergence_plan`.

## Schema changes

Wrap every core-content field in `Character`, `PlotArchitecture`, and `Scene` in `DimensionField` (the same `{value, settled}` shape already used by `WritingStyle`/`NarrativeVoice`/`WorldBuilding`):

- **`Character`**: `role`, `external_goal`, `internal_need`, `flaw`, `arc`, `voice_notes`, `backstory` → `DimensionField`. `name` stays a plain `str` (identity, not content — there's no meaningful "unsettled name"). `relationships` (dict) stays plain and **ungated**, like `title`/`themes` today — supplementary color, not required for readiness.
- **`PlotArchitecture`**: `structure`, `inciting_incident`, `climax`, `resolution` → `DimensionField` (the core arc — this expands the bar beyond today's structure+inciting_incident-only check). `causality_notes`, `pacing`, `turning_points` stay plain and **ungated** — connective/supplementary detail, writer's discretion.
- **`Scene`**: `setting`, `sensory_details`, `function`, `tension` → `DimensionField`. `id` and `characters_present` stay plain (identity/reference).
- **`NarrativeVoice.person`** / **`narrator_knowledge`** (bare enums, not `DimensionField`) are treated as settled once non-`None` — no schema change, just included in the readiness walk.

New fields on `StoryBible`:
- `settlement_override: bool = False`
- `settlement_override_reason: str = ""`

Set only via `update_story_bible`, and only through the turn-budget-exhaustion flow described below.

## Readiness gate

Replace `is_ready_for_writing()`'s logic with a full walk of every gated field:

- **`writing_style`**: all 6 fields settled.
- **`narrative_voice`**: `person` and `narrator_knowledge` non-`None`, plus all 5 `DimensionField`s settled.
- **`characters`**: at least one entry, and every entry's 7 gated fields settled. No fixed minimum count beyond 1 — brainstorm-agent decides how many characters the story needs; the gate verifies whatever's there is finished, not that a specific number exists.
- **`plot`**: `structure`, `inciting_incident`, `climax`, `resolution` all settled.
- **`scenes`**: at least one entry, and every entry's 4 gated fields settled. Same reasoning as characters.
- **`world_building`**: all 4 fields settled.

`is_ready_for_writing()` keeps its name and `tuple[bool, list[str]]` signature, but `missing` now returns precise dotted paths (e.g. `"characters[1].internal_need"`, `"plot.climax"`, `"writing_style.tone"`) instead of coarse labels — this is what lets brainstorm-agent's `think` step target exactly what's left each turn instead of re-deriving it from scratch.

**Deterministic gate tool.** Add `check_bible_readiness`, mirroring `check_originality_gate`'s pattern (`tools/gate.py`): a tool the orchestrator must call before delegating to `writer-agent`, returning one of:
- `BLOCKED`: not fully settled, with the dotted-path list of what's missing.
- `PROCEED`: fully settled.
- `PROCEED (OVERRIDDEN)`: `settlement_override` is `true` — includes the still-unsettled list and `settlement_override_reason`, so it's visible in the final report.

This keeps enforcement deterministic rather than trusting the orchestrator's own judgment of "is this ready," the same reasoning that motivated `check_originality_gate`.

**In `from_source` mode**, extraction can mark a field `settled: true` directly when the source clearly supports it (`extractor.md` already distinguishes confident extraction from ambiguous/silent) — no separate confirmation pass is required for what the source unambiguously answers. `brainstorm-agent`'s settle-pass then only needs to handle whatever extraction left `settled: false`.

## Turn-budget exhaustion (no-deadlock path)

Two existing gaps need fixing for this to work at all:
1. `settings.max_brainstorm_turns` (`config.py:43`) is never actually passed to `brainstorm-agent` today — `orchestrator.md` must include it in the delegation task text.
2. "Generate from current point" needs a real, auditable mechanism, not an assumption that the orchestrator remembers a user's free-text answer.

Flow:
1. `brainstorm-agent` self-tracks how many `ask_human` calls it has made this invocation, against the budget given in its task.
2. When it's about to exceed the budget, instead of asking another domain question, it asks one meta-question with exactly three options, each with its consequence stated in the `why` text:
   - **"Keep going a while longer"** — raises the effective budget by a fixed increment (+20 turns); consequence: more questions, more time, fuller bible.
   - **"You decide the rest"** — triggers autonomous settlement (below) for every remaining unsettled field; consequence: no more questions, but some choices are the AI's own.
   - **"Generate from here as-is"** — sets `settlement_override: true` and `settlement_override_reason` to a short note on what's left unsettled; consequence: the story may be inconsistent or generic on whatever's left, and `writer-agent` will improvise those parts.
3. This is the same mechanism regardless of whether it fires during `from_scratch`'s initial fill or `from_source`'s post-extraction settle-pass, since both go through `brainstorm-agent`.

**Autonomous settlement fallback** (also used for "you decide" mid-conversation and for non-interactive `NO_HUMAN_AVAILABLE` sessions, which already exist): make a specific, considered choice for the remaining field, consistent with everything already established, mark it `settled: true`, and note the assumption in the final report. This guarantees the gate is always eventually satisfiable in bounded turns.

## Brainstorm-agent flow changes

**Context mining (new first-turn step).** Before the first `ask_human` call, read the initial context and do two passes: (1) pull out anything stated as fact and settle those fields directly via `update_story_bible`, no question asked; (2) for what the context implies but doesn't state, form the same kind of confident, specific proposal the agent would otherwise open with, rather than treating a sparse context as equivalent to no context. Only then move to the normal question loop for what's still open. This applies the same way regardless of whether the context is a one-liner or a detailed paragraph — the detailed case just yields more directly-settled material.

**Multi-purpose proposals.** Promote the existing "weave dimensions together" guidance (`brainstorm.md:57-58`) from a stylistic aside to an explicit step in the pre-turn `think`: before proposing, check which other unsettled fields this proposal could plausibly resolve at once (e.g. one antagonist proposal settling a character, a plot turning point, and a world-rule together), shape the question to ask for all of them as one coherent creative choice, and apply every field it resolves in the same `update_story_bible` call once answered.

## from_source flow changes

Revised sequence:
1. `extractor-agent` extracts, settling whatever the source clearly supports.
2. Orchestrator calls `check_bible_readiness` and checks `divergence_plan` completeness — two independent gaps now, not one.
3. Delegate to `brainstorm-agent` scoped to whichever gaps exist: negotiate `divergence_plan` if incomplete, settle remaining dimension fields if any, both if both are open, or skip the delegation entirely if extraction alone left everything settled. If `divergence_plan` was pre-set (batch/dataset runs), it stays final and unrenegotiated; the settle-pass covers dimension gaps only.
4. Re-check `check_bible_readiness` before `writer-agent`.
5. `writer-agent` drafts, `editor-agent` reviews + fidelity check, as today.

## Non-goals / accepted limitations

- No migration path for `story_bible.json` files from sessions started before this change. The field-type change (`str` → `DimensionField`) makes old files fail validation under `extra="forbid"`. Session directories are ephemeral working artifacts; in-progress sessions from before this change would need to be restarted.
- No change to `check_originality_gate` or `check_fidelity_alignment` — this spec only touches the writer-readiness gate.

## Testing

- `tests/test_dimensions.py`: update the two existing `is_ready_for_writing` tests for the new `DimensionField`-wrapped construction and dotted-path `missing` output; add coverage for full settlement across all six dimensions and for `settlement_override` (PROCEED-OVERRIDDEN case).
- New/extended gate-tool tests mirroring `tests/test_gate_tool.py`'s pattern: BLOCKED / PROCEED / PROCEED (OVERRIDDEN) for `check_bible_readiness`.
- `tests/test_bible_tool.py` / `test_update_story_bible.py`: update fixtures building `Character`/`PlotArchitecture`/`Scene` with plain strings to the new `DimensionField` shape.
- Prompt files (`brainstorm.md`, `orchestrator.md`, `extractor.md`, `writer.md`) aren't unit-testable — a manual dry-run session (from_scratch and from_source, interactive and non-interactive) is needed once implemented, since the behavior change lives mostly in agent instructions.
