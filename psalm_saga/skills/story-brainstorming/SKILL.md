---
name: story-brainstorming
description: Use before writing any story - elicits explicit creative choices across the six PSALM infringement-oriented dimensions (writing style, narrative voice, character, plot structure, scene sequence, world-building) into a spec document, before any plan or prose is written.
---

# Story Brainstorming

Turn a premise into a dimension spec through collaborative dialogue, with fixed sections: the six dimensions PSALM (Scharrenberg & Sun) uses to evaluate stylistic and structural similarity between texts (its §3.3 infringement-oriented evaluators). Deciding them now, on purpose, is what makes a later PSALM run (or a human editor's read) measure intent rather than accident.

<HARD-GATE>
Do NOT invoke `writing-story-plans` or write any prose until every dimension below has an explicit answer and your human partner has approved the spec. Ceremony scales with the length and stakes of the piece — flash fiction gets one or two sentences per dimension, a novel gets paragraphs — but no dimension gets skipped outright.
</HARD-GATE>

<EXTREMELY-IMPORTANT>
Do this yourself, directly in the conversation with your human partner. Never dispatch this skill (or any part of it) to a subagent via `task` — a subagent cannot ask your human partner anything and would have to fabricate every dimension's answer, producing a spec nobody actually agreed to.
</EXTREMELY-IMPORTANT>

**Announce at start:** "I'm using the story-brainstorming skill to build the dimension spec."

**Save the spec to:** `docs/psalm-saga/<slug>-spec.md`

**Reference files:** `references/writing-style.md`, `references/narrative-voice.md`, `references/character.md`, `references/plot-structure.md`, `references/scene-sequence.md`, `references/world-building.md` — one per dimension below, each with fuller definitions, examples, common pitfalls, and the literature the dimension is grounded in. Read the relevant reference file the first time you work each dimension in a session; the bullet points below are a checklist, not the full explanation.

## Process

1. **Premise.** Ask what the person is trying to write and why: audience, length, genre, what a satisfying read *feels* like when it's done. Don't skip to dimensions before the premise is clear.
2. **Derivative check.** Ask directly: is this based on, inspired by, a continuation of, or a retelling of an existing work? If yes, note it now and invoke `adapting-existing-work` after finishing Step 3 below, before presenting the spec for sign-off. Don't let "just inspired by the vibe of X" slide past this question — let your human partner decide whether that counts.
3. **Walk the six dimensions, one at a time**, presenting each in a short chunk your human partner can actually read and react to (per-dimension, not all thirty-six sub-dimensions dumped at once). Read that dimension's reference file before asking its questions if this is the first time in the session you're covering it. For each dimension, ask about its sub-dimensions and write down the concrete choice, not a vague aspiration ("wry, understated" beats "funny").

### Dimension 1 — Writing Style (`references/writing-style.md`)

- **Lexical Complexity**: vocabulary richness, word-length tendencies, formality register.
- **Sentence Structure**: preferred sentence length and syntactic complexity (short and simple vs. long, multi-clause).
- **Rhythm & Flow**: punctuation density, pacing, prose rhythm.
- **Rhetorical Patterns**: use of questions, imperatives, repetition, parallelism.
- **Discourse Organisation**: paragraph structure, use of connectives.
- **Tone & Voice**: personal vs. impersonal stance, assertive vs. hedging.

### Dimension 2 — Narrative Voice (`references/narrative-voice.md`)

- **Point of View**: first / second / third person; knowledge scope (limited, multiple, omniscient, objective).
- **Narrative Distance**: how close the narrator sits to character consciousness; emotional involvement.
- **Narrator Presence**: homodiegetic (participates in events) vs. heterodiegetic (outside them); how intrusive/commenting.
- **Temporal Perspective**: primary tense; retrospective, simultaneous, or anticipatory telling.
- **Focalisation Pattern**: whose perspective filters information — fixed internal, variable internal, or external.
- **Reader Engagement**: does the narrator address the reader directly, how often, with what assumed relationship.

### Dimension 3 — Character (`references/character.md`)

- **Character Identity and Traits**: distinctive personality traits, physical idiosyncrasies, mannerisms — specific, not generic labels.
- **Character Arc and Development**: initial state, trigger, stages, resolution.
- **Character Relationships and Dynamics**: interaction patterns, power balances, emotional textures between characters.
- **Character Background and Motivation**: specific causal history and motivational structure, not just "traumatic past."
- **Character Expression and Behaviour**: behavioural signatures, habitual responses.
- **Character Function and Role**: high-level narrative function (protagonist, antagonist, mentor) — the most generic sub-dimension; don't spend much time here relative to the others.

### Dimension 4 — Plot Structure (`references/plot-structure.md`)

- **Event Sequence and Causality**: the specific chain of events and how each causes the next.
- **Story Architecture and Structure**: act division, framing devices, nested narratives, interwoven subplots.
- **Conflict Construction**: escalation pattern, obstacles.
- **Plot Turning Points and Reversals**: the pivotal shifts and revelations — the unique twists, not generic "surprises."
- **Temporal Structure**: chronology, flashbacks, pacing of time.
- **Plot Functions and Convergence**: how subplot threads converge and resolve.

### Dimension 5 — Scene Sequence (`references/scene-sequence.md`)

- **Scene Identity and Content**: setting, participants, actions, and purpose of each major scene.
- **Scene Internal Structure**: beat sequence and staging within a scene.
- **Scene Sequence Architecture**: ordering and relationship between scenes.
- **Scene Transition and Connections**: linking devices and continuity between scenes.
- **Scene Pacing and Rhythm**: patterns of scene length and tempo.
- **Scene Functions and Types**: standard scene categories used (climax, denouement, etc.) — genre-typical and weakly distinctive; don't over-invest here.

### Dimension 6 — World-Building (`references/world-building.md`)

- **Geographic and Spatial Design**: locations, spatial layout, environment.
- **World Rules and System**: magic/technology/physics rules, costs, capabilities, limitations.
- **Cultural and Social Architecture**: customs, rituals, institutions, hierarchies.
- **Historical and Temporal Design**: past events, cycles, eras.
- **Material and Sensory Detail**: objects, flora/fauna, sensory atmosphere.
- **World Function and Logic**: how the world stays internally coherent — the most abstract sub-dimension; brief is fine.

4. **Write the spec** to `docs/psalm-saga/<slug>-spec.md` with one section per dimension, each sub-dimension as a bullet with the agreed choice in the human partner's own words wherever possible. Head the file with a one-line note that these sections mirror PSALM §3.3.
5. **Get explicit sign-off** before invoking `adapting-existing-work` (if flagged in step 2) or `writing-story-plans`. Show the spec, don't assume silence is approval.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just start writing, style will emerge naturally" | It will — inconsistently. Decide it now so `reviewing-story-dimensions` has something to check against. |
| "The character function is obviously 'protagonist', skip it" | Fine to answer briefly, but still write it down — don't silently drop a dimension. |
| "This dimension doesn't apply to this story" | Rare, but possible (e.g. a plotless mood piece may have thin Plot Structure). Say so explicitly in the spec rather than leaving the section blank. |
| "The person just wants a quick draft, skip the spec" | Ceremony scales down, not to zero — even a quick draft benefits from one sentence per dimension, and it's the cheapest possible insurance against a story that reads like nothing was decided. |
| "I've read the dimension list before, I don't need the reference file again" | Fine to skip on repeat sessions once you've internalised it — but the first time through each dimension in a session, read the reference; the bullets alone under-specify concepts like focalisation vs. point of view that are easy to conflate. |

## Handoff

End by stating explicitly: "Spec complete. [Invoking adapting-existing-work next. / Ready for writing-story-plans.]"
