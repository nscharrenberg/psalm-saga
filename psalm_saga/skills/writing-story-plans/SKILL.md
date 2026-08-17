---
name: writing-story-plans
description: Use after story-brainstorming has produced a signed-off dimension spec - converts that spec into a whole-story plan and a per-chapter breakdown that carries every dimension's commitments into concrete beats, before any prose is drafted.
---

# Writing Story Plans

Turn a signed-off dimension spec into a plan concrete enough that a chapter-writer subagent with no memory of the brainstorming conversation could pick up any single chapter brief and know exactly what to write, assuming zero context beyond what the brief itself says.

**Announce at start:** "I'm using the writing-story-plans skill to turn the spec into a story plan."

**Save plans to:** `docs/psalm-saga/<slug>-plan.md`

## Scope Check

If `docs/psalm-saga/<slug>-spec.md` doesn't exist or wasn't signed off, stop and invoke `story-brainstorming` first — this skill does not infer dimension choices from a vague premise.

## Process

1. **Read the full spec**, including the Source Relationship section if `adapting-existing-work` was used.
2. **Write the whole-story plan**: title, logline, chapter list with a one-line summary each, and a **dimension carry-through table** — for each of the six dimensions, one row stating how the plan embodies the spec's choice. Example: if the spec's Plot Structure chose "three-act with a frame narrative," the row names exactly where the act breaks fall and where the frame device opens and closes. A plan that can't point to where a spec choice actually shows up hasn't carried it through — revise until it can.
3. **Write a per-chapter brief for every chapter**, each containing:
   - **POV / focalisation for this chapter** — must match the spec's Narrative Voice choice unless a shift is a deliberate, explicitly noted structural device (e.g. an epistolary chapter). Unexplained POV drift between chapters is a defect, not a stylistic choice.
   - **Scenes in this chapter** — identity/content, internal structure, how each transitions to the next, and pacing (Scene Sequence sub-dimensions).
   - **Characters present** and which part of their arc, relationships, or motivation advances here (Character sub-dimensions) — don't let a character appear with nothing to do relative to their spec'd arc.
   - **Plot events landing here** — which event-sequence beats, turning points, or convergences from the spec's Plot Structure land in this chapter.
   - **World-building elements** established or paid off here (World-Building sub-dimensions) — note setups that need a later payoff so `drafting-chapters` doesn't lose track of them across chapters.
4. **Show the plan to your human partner in reviewable chunks** (per act or per few chapters, not the whole plan at once for long works) and get explicit sign-off before invoking `drafting-chapters`.
5. Save the final version to `docs/psalm-saga/<slug>-plan.md`, referencing the spec's dimension language by name (e.g. "Narrative Distance: close, per spec") so `reviewing-story-dimensions` can check chapters against the plan without re-deriving the spec's intent from scratch.

## Continuity Budget

For long works, decide now how later chapters will get continuity context without re-reading every prior chapter in full: a running one-paragraph continuity summary updated after each chapter, maintained as part of the plan file, is usually enough. Note the approach in the plan so `drafting-chapters` knows what to hand each writer subagent.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll structure this as I draft, the plan can stay loose" | A loose plan is exactly what lets dimension drift happen unnoticed between chapters — that's the failure mode this whole skill set exists to prevent. |
| "This chapter doesn't need a brief, it's just a short bridge scene" | Bridge scenes still have a POV, still touch characters, still cost world-building or plot budget. Write the brief, even if it's three lines. |
| "The dimension carry-through table is busywork" | It's the check that the spec's choices actually reached the plan rather than staying aspirational. If a row is hard to fill in, that's a sign the plan hasn't actually committed to that dimension yet. |
