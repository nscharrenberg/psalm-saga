---
name: reviewing-story-dimensions
description: Use after a chapter or a full story draft exists, to check it against the dimension spec and plan produced by story-brainstorming and writing-story-plans - a coverage checklist (covered / partial / missing) per PSALM dimension and sub-dimension, not a numeric similarity score.
---

# Reviewing Story Dimensions

Check a draft against its *own* spec and plan, applied to prose and the six (or ten, if adapting) PSALM-aligned dimensions.

**Announce at start:** "I'm using the reviewing-story-dimensions skill to check this against the spec."

## What This Skill Is Not

This is not PSALM. PSALM (Scharrenberg & Sun, "Probing Stylistic Appropriation using Large Language Models") is an LLM-as-judge *measurement* framework: it scores similarity between two texts — typically a generated story and a separate source work — on a weighted five-level scale (0, 3, 5, 8, 10) via a DAG of sub-dimension task nodes and a judgement node. This skill instead checks a single text against its *own stated intentions*: did the draft deliver what the spec and plan committed to, not how similar is this text to some other text. If your human partner wants an actual PSALM run — for instance to audit an adaptation's similarity to its named source, or to check for unintended stylistic appropriation — point them at the PSALM framework itself rather than trying to approximate its scoring here.

## Process

For each dimension the spec covers (Writing Style, Narrative Voice, Character, Plot Structure, Scene Sequence, World-Building, plus the Source Relationship dimensions if `adapting-existing-work` was used — see `story-brainstorming/references/` and `adapting-existing-work/references/` if you need the fuller definition of any sub-dimension while checking coverage), and for each of its sub-dimensions:

1. Mark **Covered / Partial / Missing** against what the spec (and, if reviewing a specific chapter, that chapter's brief) committed to.
2. Give a one-line note that cites the relevant passage (quote sparingly and briefly, or paraphrase) and names the spec commitment it's being checked against.
3. **If the spec locked any dimensions from a source text** (`story-brainstorming`'s Source-Derived Variance Check was used — the spec will say a dimension is "preserved"/"unchanged" from a named source), re-read the source text itself for those dimensions and check the draft against the source's actual register directly, not only against the spec's paraphrase of it. A paraphrase can drift from what the source actually does (e.g. "understandable communication" quietly permitting dialogue the source never had) without the draft ever contradicting the paraphrase's own wording — checking only against the paraphrase would mark that "Covered" when it isn't faithful to the locked dimension at all. Treat a locked dimension's sub-dimensions (discourse form, dialogue density, rhetorical pattern, etc.) as findings against the source text, same severity as any other Missing/Partial.

Produce a findings table ordered by severity — Missing findings on core dimensions first, then Partial, then any Source Relationship findings if applicable.

**If dispatched as a review subagent, report only — do not fix the text yourself.** The drafting side decides how to address findings.

## Handling Findings

- **Missing on a core dimension** blocks moving to the next chapter or calling the story done. Send back to `drafting-chapters` for a fix pass.
- **Partial** is a judgement call: is it an intentional variation the brief allowed (e.g. a deliberate one-chapter POV shift, already noted in the plan), or a real gap? If unclear, ask — don't assume either answer.
- **Source Relationship findings** (adaptations only): flag explicitly if the checklist shows the draft reading *more* evocative or similar to the source than the declared relationship intended — for example, the spec named "pastiche, homage tone" but the draft reads closer to mockery, or an intended "transformative retelling" reads as a near-scene-for-scene copy. This is exactly the kind of drift PSALM's own experiments found supervised fine-tuning induces even without any deliberate intent to copy — catching it here, at the checklist level, is the inexpensive check to run before anyone considers an actual PSALM comparison against the source.

## Red Flags

| Thought | Reality |
|---------|---------|
| "It's close enough to what the spec wanted" | "Close enough" was already decided when the spec was signed off. Check the draft against what was actually written down, not against a looser mental version of it. |
| "I can just fix it myself while reviewing" | If dispatched as a review subagent, report findings only — fixing is `drafting-chapters`' job, so the fix goes through the same review loop as everything else. |
| "This dimension barely matters for this story" | If the spec covered it, check it. If it genuinely doesn't apply, that should have been noted explicitly in the spec (see `story-brainstorming`'s red flags) — not silently skipped at review time. |
| "The draft matches the spec's wording, so it's Covered" | Matching the spec's wording isn't the same as matching the source, for any dimension the spec locked as preserved/unchanged. Re-check those against the actual source text — the spec's paraphrase of it may already have drifted. |
