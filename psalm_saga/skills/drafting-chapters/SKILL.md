---
name: drafting-chapters
description: Use after writing-story-plans has produced a signed-off story plan - dispatches a fresh writer subagent per chapter, carrying the spec and that chapter's brief, followed by a dimension-coverage review before moving to the next chapter.
---

# Drafting Chapters

Execute the plan by dispatching a fresh writer subagent per chapter, reviewing each chapter's dimension coverage before moving on, and running one whole-story review at the end.

**Why subagents:** each chapter-writer gets exactly the context it needs (spec, plan, this chapter's brief, and a continuity summary) and nothing else — not your full brainstorming conversation, not every prior chapter's full text unless the continuity budget in the plan calls for it. This keeps each chapter's prose anchored to the spec rather than drifting toward whatever the growing transcript happens to suggest.

**Announce at start:** "I'm using the drafting-chapters skill to write the story."

## Scope Check

If `docs/psalm-saga/<slug>-plan.md` doesn't exist or wasn't signed off, stop and invoke `writing-story-plans` first.

## Autonomous Mode

Only active when `batch-story-generation` is the force-injected bootstrap
for this session (a `psalm-saga-batch` run); ignore this section in every
other session.

**Scope Check override:** check for
`docs/drafts/<story_name>/<story_name>-plan.md` instead of
`docs/psalm-saga/<slug>-plan.md`.

**Save chapter files under `docs/drafts/<story_name>/`**, alongside the
spec, plan, and (later) review report for this story.

**Step 3's "ask your human partner if genuinely unclear" does not apply
here.** There is no one to ask. `reviewing-story-dimensions`'s Autonomous
Mode section is the authority on how `Partial`/`Missing` findings are
handled and when a chapter fix attempt is exhausted (its 3-attempt cap
and `ABANDONED.md` rule) — follow that instead of pausing for a judgement
call. Everything else in this skill (dispatching `chapter-writer`,
dispatching `reviewing-story-dimensions` after each chapter, updating the
continuity summary, the final whole-story review) is unchanged.

## The Loop, Per Chapter

1. **Dispatch a chapter-writer subagent** with: the dimension spec (or the relevant excerpts if it's long), the whole-story plan's dimension carry-through table, this chapter's brief in full, and the continuity summary from the plan (not every prior chapter's full prose, unless the brief specifically calls for re-reading an earlier chapter for a callback). The writer's only job is to draft this chapter's prose — it does not dispatch its own subagents and does not review its own work against the spec.
2. **On return, dispatch `reviewing-story-dimensions`** with the chapter draft, the spec, and this chapter's brief.
3. **Handle the report:**
   - **Missing** on a dimension the brief committed to → send it back: either a fix pass in the current context (small gap) or a fresh writer dispatch that names the gap explicitly (larger gap, or if the current draft's approach is fundamentally off).
   - **Partial** → your call whether it's an intentional variation the brief allows or a real gap; ask your human partner if genuinely unclear, don't assume either way.
   - Don't let findings accumulate silently across chapters — fix or explicitly accept each one before moving to the next chapter.
4. **Update the continuity summary** in the plan file with what this chapter actually established (not just what the brief planned — note any deviations), so the next chapter's dispatch reflects reality.
5. **Move to the next chapter.**

## After All Chapters

Once every chapter has passed its per-chapter review, dispatch `reviewing-story-dimensions` once more for the **whole story**, checking cross-chapter consistency specifically: does Narrative Voice actually stay consistent (or intentionally shift) across chapters as the spec described; does a World-Building element set up early get paid off later; do Character arcs resolve the way the spec's arc/development sub-dimension described. This final pass catches issues no single chapter's isolated review could see.

## Model Selection

Use your most capable available model for the chapter-writer dispatches — prose quality and voice consistency are exactly what's being tested. A faster/cheaper model is usually adequate for the `reviewing-story-dimensions` checklist pass, since it's a structured coverage check against an explicit spec rather than open-ended creative judgement.

## Red Flags

| Thought | Reality |
|---------|---------|
| "It's a short story, I'll just write it myself in one go, no dispatch" | Reasonable for very short pieces with one "chapter." For anything with multiple chapters, per-chapter isolation is what stops each new chapter from uncritically inheriting drift from the last. |
| "The review found something minor, I'll just note it and move on" | Minor findings are fine to accept explicitly — but *explicitly*, not silently skipped. Say why it's acceptable. |
| "I'll skip the whole-story review, every chapter already passed" | Per-chapter review can't see cross-chapter drift (a Voice that's individually fine in each chapter but different chapter to chapter). The final pass is not redundant with the per-chapter ones. |
