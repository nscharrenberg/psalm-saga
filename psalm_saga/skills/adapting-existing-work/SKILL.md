---
name: adapting-existing-work
description: Use when a story is explicitly based on, inspired by, or a continuation/adaptation of an existing work - elicits explicit choices across PSALM's four defence-oriented dimensions (parody/satire, pastiche, quotation/citation, scenes-a-faire) so the relationship to the source is a documented creative decision, not an accident.
---

# Adapting an Existing Work

Invoked from within `story-brainstorming`, step 2, when the story is derivative of an identifiable existing work. Never invoked as a stand-alone first step — the six core dimensions (`story-brainstorming`) come first; this skill adds a "Source Relationship" section to the same spec.

**Announce at start:** "I'm using the adapting-existing-work skill to record how this relates to its source."

**Reference files:** `references/parody-and-satire.md`, `references/pastiche.md`, `references/quotation-and-citation.md`, `references/scenes-a-faire.md` — one per relationship path below, each explaining the underlying legal doctrine (the CJEU case law and Directive articles PSALM's evaluators operationalise) in more depth than the bullet points here. `references/scenes-a-faire.md` applies to every adaptation regardless of which path is chosen; read the relevant path-specific file for whichever relationship your human partner picks in step 2 below.

<EXTREMELY-IMPORTANT>
This skill is not legal advice and does not determine whether a finished story would infringe anything. It exists to make the intended relationship to the source explicit and on the record — PSALM's own findings (Scharrenberg & Sun) show that fine-tuned generation drifts toward high similarity on the six core dimensions while defence-relevant qualities (evocation, transformation, homage, attribution) stay low *unless deliberately cultivated*. If the intended use is commercial and the source is not clearly public domain, tell your human partner to get real legal review before publication — say this plainly, once, and move on.
</EXTREMELY-IMPORTANT>

## Process

1. **Name the source** and confirm its status if known (public domain, actively copyrighted, unclear) — don't guess at legal status, just record what's known and flag what isn't.
2. **Ask which relationship is intended.** Present as an explicit choice, not an assumption:
   - **Homage / pastiche** — imitating the source's style as a tribute, with new content. See `references/pastiche.md`.
   - **Parody / satire** — evoking the source specifically to comment on or mock it (or something else, using it as a vehicle). See `references/parody-and-satire.md`.
   - **Transformative retelling** — using the source's plot/characters/world as raw material for a substantially new story. `references/scenes-a-faire.md` is the most relevant reference here — the question is mainly how much of what's shared with the source is generic genre furniture versus specific creative choices.
   - **Quotation-bounded excerpt** — reproducing specific passages for criticism, review, or similar purpose, clearly marked and attributed. See `references/quotation-and-citation.md`.
   - **Loosely inspired, not really derivative** — if the human partner picks this, record the source as an influence note and skip the rest of this skill; return to `story-brainstorming`.
3. **For the chosen path (except the last), read that path's reference file, then elicit its sub-dimensions** and write the answers into the spec's Source Relationship section:

### If parody / satire (`references/parody-and-satire.md`)

- **Source Work Evocation / Recognition**: how will the reader recognise the source — named references, distinctive characters, iconic settings, recognisable stylistic imitation?
- **Noticeable Differences / Transformation**: what's substantively changed in character, plot, setting, or message — not just cosmetic changes?
- **Humorous Character**: what devices carry the humour (exaggeration, irony, absurdity, wordplay), and how strong?
- **Mocking / Critical Character**: what is being critiqued — the source, its author, a genre, or a broader phenomenon — and how?
- **Fair Balance and Context**: is the extent of borrowing proportionate to the parodic purpose? Note explicitly if the parody risks discriminatory content against any group — that's a hard stop to flag, not a style note.

### If pastiche (`references/pastiche.md`)

- **Style Evocation and Recognition**: which source-specific stylistic signatures (rhythm, lexicon, tone, technique) are being imitated?
- **Artistic Skill and Execution**: how will the imitation stay coherent and adapt naturally to new content, rather than reading as clumsy mimicry?
- **Homage / Tribute Character**: what signals respect or admiration, and confirms the absence of mockery?
- **Noticeable Differences / Transformation**: what content (characters, plot, themes) differs from the source despite the stylistic echo?
- **Fair Balance and Proportionality**: how much stylistic borrowing relative to new content?

### If quotation-bounded excerpt (`references/quotation-and-citation.md`)

- **Quotation Identification and Extraction**: which passages, if any, will be reproduced verbatim/near-verbatim, and how will they be marked (quotation marks, block-quote convention)?
- **Legitimate Purpose**: criticism, review, teaching, research, or similar — state it explicitly.
- **Fair Practice and Proportionality**: is the extent of quotation proportionate to that purpose, and is it integrated into original commentary rather than standing alone?
- **Attribution and Source Acknowledgement**: how will the source work and author be credited?
- **Fair Balance and Justification**: could this substitute for the original in the market? Flag if so.
- **Work Already Disclosed**: confirm the source appears to have been lawfully made available to the public already.

### Always ask (any adaptation, regardless of path — `references/scenes-a-faire.md`)

- **Genre Conventions and Setting / Stock Characters and Archetypes / Standard Plot Devices and Tropes / Thematic Commonplaces / Necessary Technical Elements**: which elements are standard genre furniture rather than distinctive to the source — these are the least legally protectable and least interesting to imitate precisely.
- **Creative Elaboration**: what will make *this* execution more than generic stock? Feed the answer back into the six core dimensions in the main spec (see `story-brainstorming/references/`) — this is the connective step; genericness in the source material is not an excuse for genericness in the new story.

4. **Append** the answers as a "## Source Relationship" section in the same `docs/psalm-saga/<slug>-spec.md` file `story-brainstorming` is building, under a subheading naming the chosen relationship type.
5. **Return to `story-brainstorming`** for final sign-off of the complete spec (core dimensions + source relationship together).

## Red Flags

| Thought | Reality |
|---------|---------|
| "The source is old, so it's probably fine" | Age isn't the same as confirmed public-domain status. Record what's known; don't determine it. |
| "It's obviously a parody, no need to spell out the humour" | "Obviously" to the writer isn't "obviously" to a reader or a later reviewer — write down the actual devices. |
| "We're just using the setting, not the characters, so scènes à faire doesn't apply" | Scènes à faire is asked for every adaptation regardless of path — it's the check for whether *any* borrowed element is doing more than generic genre work. |
