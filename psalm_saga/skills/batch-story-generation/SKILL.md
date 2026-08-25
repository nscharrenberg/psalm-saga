---
name: batch-story-generation
description: Force-injected as the bootstrap only by the psalm-saga-batch command - runs the full spec-to-final-story pipeline for one story at a time with no human interaction, deciding every dimension itself under one of four input modes (scratch, context, template, variant), and never asking a question.
---

# Batch Story Generation

<INTERACTIVE-SESSION-STOP>
This skill is force-injected as the active bootstrap only by the
`psalm-saga-batch` command, replacing `using-psalm-saga` for that session
entirely. If you are having a normal conversation with a human in an
interactive `psalm-saga` session, ignore this skill — it does not apply,
and you should be following `using-psalm-saga` (which asks questions and
waits for sign-off) instead.
</INTERACTIVE-SESSION-STOP>

<EXTREMELY-IMPORTANT>
You will never see a human response in this session. Every decision a
human would normally make in `story-brainstorming`, `writing-story-plans`,
or `reviewing-story-dimensions` — every dimension, every sign-off, every
judgement call on an ambiguous review finding — is yours to make. Do not
ask a question and wait; decide, write it down, and keep going.
</EXTREMELY-IMPORTANT>

## What you'll receive

The CLI sends one instruction message per story, on this same session
thread, shaped like:

> Generate story {i} of {count}. Mode: {scratch|context|template|variant}.
> Combine: {mixed|separate}. Inputs: [...]. Existing names in this
> session: [...].

The message may also include a `Story length directive: ...` line (from
the run's `--length`/`--chapters` flags) — treat it as locked input
exactly like `Mode`/`Combine`/`Inputs`: `story-brainstorming` and
`writing-story-plans` state it back rather than deciding it themselves.

`Combine: separate` means the `Inputs` you were given for this specific
story are already narrowed to just this story's share — treat them as the
whole pool for this story, don't expect to see the rest. `Combine: mixed`
means the full pool was given to you and you may draw on any part of it.

Generate exactly the one story that message describes, then stop — end
your turn with a short summary (story name, whether it was promoted or
abandoned, and why). The CLI's own loop decides whether and how to ask for
the next one; do not generate more than one story per instruction message.

## The pipeline, per story

Every story still goes through the same pipeline stages interactive
sessions do — batch mode changes who decides and whether there's a pause,
not whether the process happens:

1. **Autonomous brainstorming** — invoke `story-brainstorming`, following
   its `## Autonomous Mode` section, which covers all four input modes
   (scratch/context/template/variant) in detail. Produces
   `docs/drafts/<story_name>/<story_name>-spec.md`.
2. **Autonomous planning** — invoke `writing-story-plans`, following its
   `## Autonomous Mode` section. Produces
   `docs/drafts/<story_name>/<story_name>-plan.md`.
3. **Drafting** — invoke `drafting-chapters`, following its
   `## Autonomous Mode` section (save path and Scope Check path only —
   the per-chapter loop itself is the same as an interactive session).
   Dispatches the `chapter-writer` subagent per chapter, same as an
   interactive session.
4. **Autonomous review-and-fix** — invoke `reviewing-story-dimensions`,
   following its `## Autonomous Mode` section, per chapter and once for
   the whole story. Produces/updates
   `docs/drafts/<story_name>/<story_name>-review.md`.
5. **Finish** — once the whole-story review is fully clean, write a
   short `docs/drafts/<story_name>/DONE.md` (a sentence is enough, e.g.
   "Whole-story review passed clean.") as the very last action, then end
   your turn. This file is the only thing that marks a draft as
   promotable — promotion happens outside this conversation, and only for
   a draft that carries `DONE.md`: it reads the plan's title heading and
   every `chapter-<N>-<slug>.md` file (in order) and assembles them into
   a single reader-facing `docs/stories/<story_name>.md` — the title,
   then the chapters, the way a reader gets the finished book. The spec,
   plan, review report, and `DONE.md` itself stay only in
   `docs/drafts/<story_name>/`; you do not write `docs/stories/` yourself
   and nothing from the draft directory is copied there verbatim. If the
   review never converges (see the fix-loop cap in
   `reviewing-story-dimensions`'s Autonomous Mode), write `ABANDONED.md`
   instead — never both — and end your turn without further action. A
   draft with neither file (e.g. one interrupted mid-pipeline by an
   unexpected error) is simply left as-is: not abandoned, not promoted,
   not retried.

<EXTREMELY-IMPORTANT>
Brainstorming and planning still happen directly in your own turn, never
dispatched to a subagent — the reasoning is the same as in interactive
mode (a dispatched subagent can't carry context back into this
conversation for the next stage), it just no longer depends on needing a
human to talk to. `chapter-writer` and `dimension-reviewer` remain the
only subagents this pipeline ever dispatches, exactly as in interactive
mode.
</EXTREMELY-IMPORTANT>

## Story naming

Pick a kebab-case `story_name` from the story's own premise once you've
settled on one (same convention interactive sessions use for `<slug>`).
Check it against the "Existing names in this session" list the CLI gave
you — if it collides, pick a different one before writing any file.

## Diversity across a batch

Before locking a scratch-mode premise, and as a light sanity check for the
other modes too, read `docs/drafts/_batch-log.md` if it exists (there is
none for the first story of a session). It's a plain running log, one line
per story: `<story_name>: <genre> / <narrative voice> / <one-line
premise>`. If your new story's combination reads as a near-duplicate of an
existing line (same genre, same narrative voice, same core conflict
shape), reroll before locking anything. After promoting (or abandoning)
this story, append its own line.

## Red Flags

| Thought | Reality |
|---------|---------|
| "This dimension is ambiguous, I'll leave a note and move on" | There's no one to resolve it later. Pick a concrete answer yourself, document the reasoning inline, and proceed. |
| "I'll dispatch a subagent to do the brainstorming for this story, it's faster" | Still no — subagents can't carry state into your next pipeline stage, whether or not a human is involved. Do it inline. |
| "This review finding is only Partial, batch mode can let that slide" | Autonomous Mode treats Partial the same as Missing — see `reviewing-story-dimensions`. Fix it or abandon the story; never promote it as-is. |
| "I've generated 3 stories already, this 4th one can reuse the same voice, it's fine" | Check `_batch-log.md` first. A batch is supposed to be diverse, not ten variations on the same idea. |
