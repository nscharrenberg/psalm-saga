---
name: using-psalm-saga
description: Use when starting any creative-writing or story task - establishes the mandatory spec-first order (dimensions before plan, plan before prose, prose before review) and requires invoking a psalm-saga skill before any response, including clarifying questions.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific writing or review task, ignore this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a psalm-saga skill might apply to what you are doing, you ABSOLUTELY MUST invoke it.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. You cannot rationalize your way out of this by deciding the story is "simple" or "just a short piece."
</EXTREMELY-IMPORTANT>

## The Rule

**Invoke relevant or requested psalm-saga skills BEFORE any response or action** — including clarifying questions, sketching a premise, or writing a single line of prose. If it turns out wrong for the situation, you don't have to use it.

**Before any prose is drafted:** if a dimension spec doesn't already exist for this story, invoke `story-brainstorming` first. If the story is explicitly based on, inspired by, or a continuation of an existing work, `story-brainstorming` will tell you to invoke `adapting-existing-work` as part of building that spec.

**Before any chapter is drafted:** if a story plan carrying the spec's choices into chapters doesn't already exist, invoke `writing-story-plans` first.

**Before calling a chapter or the story done:** invoke `reviewing-story-dimensions`.

Then announce "Using [skill] to [purpose]" and follow the skill exactly. If it has a checklist, create a todo per item.

<EXTREMELY-IMPORTANT>
**Never dispatch `story-brainstorming`, `adapting-existing-work`, or plan sign-off to a subagent via `task`.** A dispatched subagent runs to completion in isolation and returns a final report — it has no channel back to your human partner and cannot pause mid-task to ask a question. If you delegate brainstorming to a subagent, the subagent cannot actually elicit your human partner's answers to the dimension questions; it can only fabricate plausible-sounding ones and hand back a "finished" spec that reflects none of your partner's actual intent. This defeats the entire point of this skill set. The elicitation dialogue, the spec, the plan, and every sign-off MUST happen directly in this conversation, one exchange at a time. The only steps this skill set ever dispatches to a subagent are drafting a single chapter (`chapter-writer`, from within `drafting-chapters`) and checking a draft against its spec (`dimension-reviewer`, from within `reviewing-story-dimensions`) — both of which are fully specified upfront and genuinely need no further input mid-task. If you notice yourself reaching for `task` before a spec exists, or before a plan has been signed off, stop — that is the same rationalization the Red Flags table below warns about, just wearing a "delegate for efficiency" costume.
</EXTREMELY-IMPORTANT>

## Why dimensions come first

This skill set exists so a finished story can be evaluated afterward — by a human editor or by an automated framework such as PSALM (Scharrenberg & Sun, "Probing Stylistic Appropriation using Large Language Models," which this skill set is named after) — against choices the author actually made on purpose, not choices that emerged as an accident of however the model happened to continue the prose. PSALM measures six dimensions of expressive similarity (writing style, narrative voice, character, plot structure, scene sequence, world-building) and, for adaptations, four dimensions of statutory defence (parody/satire, pastiche, quotation/citation, scènes à faire). `story-brainstorming` and `adapting-existing-work` elicit exactly these dimensions as a spec before anything is written — with reference files elaborating each one from the literature PSALM itself draws on — `writing-story-plans` carries that spec into concrete chapters; `reviewing-story-dimensions` checks the prose against the spec's own commitments. None of these skills run PSALM itself — they exist so that if someone later does run PSALM (or just reads the story with the dimensions in mind), the result reflects deliberate authorial choices.

## Skill Order

1. `story-brainstorming` — always first. Produces the dimension spec. Its `references/` directory has one file per dimension (writing-style, narrative-voice, character, plot-structure, scene-sequence, world-building) with definitions, examples, and literature grounding beyond the bullet points in the skill body itself — read the relevant one while working that dimension.
   - `adapting-existing-work` — invoked from within brainstorming, only if the story is derivative of an existing work. Its `references/` directory similarly elaborates each defence dimension (parody-and-satire, pastiche, quotation-and-citation, scenes-a-faire) with the underlying legal doctrine.
2. `writing-story-plans` — turns the signed-off spec into a whole-story plan and per-chapter briefs.
3. `drafting-chapters` — dispatches a writer subagent per chapter and runs a review after each.
4. `reviewing-story-dimensions` — checks a chapter or the whole story against the spec/plan's own commitments. Invoked from within `drafting-chapters` per chapter, and once more at the end for the whole story.

Process skills come before prose. "Let's write a story about X" → `story-brainstorming` first, always, even for a short piece — the ceremony scales with length (a flash-fiction spec might be three sentences per dimension), but the step never gets skipped outright.

## Red Flags

These thoughts mean STOP — you're rationalizing:

| Thought | Reality |
|---------|---------|
| "It's just a short story, I don't need a spec" | Ceremony scales with length; the step doesn't disappear. A three-sentence spec is still a spec. |
| "I already know what voice I want" | Knowing it in your head isn't the same as writing it down where `reviewing-story-dimensions` can check drift against it later. |
| "I'll figure out the world-building as I go" | That's exactly the kind of accretive, undocumented choice PSALM's evaluators would flag as unexamined similarity if this ever gets compared to a source. Decide it now. |
| "This is inspired by X but not really an adaptation" | If a reader could recognise X in this, `adapting-existing-work` applies. Let the human partner make that call explicitly, don't assume it away. |
| "The review is just a formality" | Missing/Partial findings on a core dimension block moving on — the review is the mechanism that keeps the spec's promises honest. |
| "I don't need the reference file, I know what 'narrative voice' means" | The reference files exist because the dimension names in the skill body are shorthand for more specific, literature-grounded concepts (e.g. Genette's focalisation vs. point of view are easy to conflate without reading the definitions). Read the reference the first time you work each dimension. |
| "I'll dispatch a subagent to handle brainstorming and planning, it's more efficient" | A subagent can't talk to your human partner — it will guess at every dimension instead of asking, and you'll end up with a spec and plan nobody actually agreed to. Do this work yourself, in this conversation. |
| "The user gave me a detailed premise already, I can just build the whole spec and plan from that" | A detailed premise is a great start for the *conversation*, not a substitute for it — it doesn't cover all six dimensions and their sub-dimensions, and your human partner hasn't seen or approved your specific choices for the ones it doesn't cover. Walk through `story-brainstorming` and get real sign-off regardless of how much detail the opening message contained. |

## Platform Adaptation

The action vocabulary this skill set uses (read a file, dispatch a subagent, write a file, track a todo list) is deliberately named generically rather than tied to one harness's tool names, so it works whether you're running under Claude Code, deepagents, or elsewhere. See `references/deepagents-tools.md` for the concrete tool-name mapping when running on LangChain's Deep Agents harness specifically.

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, direct requests) take precedence over skills, which in turn override default behavior. Only skip skill workflows when your human partner has explicitly told you to.
