---
name: story-brainstorming
description: Use before writing any story - elicits explicit creative choices across the six PSALM infringement-oriented dimensions (writing style, narrative voice, character, plot structure, scene sequence, world-building) into a spec document, before any plan or prose is written.
---

# Story Brainstorming

Turn a premise into a dimension spec through collaborative dialogue, with fixed sections: the six dimensions PSALM (Scharrenberg & Sun) uses to evaluate stylistic and structural similarity between texts (its §3.3 infringement-oriented evaluators). Deciding them now, on purpose, is what makes a later PSALM run (or a human editor's read) measure intent rather than accident.

<HARD-GATE>
Do NOT invoke `writing-story-plans` or write any prose until every dimension below has an explicit answer and your human partner has approved the spec. Ceremony scales with the length and stakes of the piece — flash fiction gets one or two sentences per dimension, a novel gets paragraphs — but no dimension gets skipped outright.
</HARD-GATE>

<HARD-GATE>
Ask, don't propose. During this dialogue you elicit and write down *their* choices — you do not generate story content, sample scenes, named rituals/systems, "suggested" sequences, or paragraphs of worldbuilding/lore on your human partner's behalf, even as an illustration. If they ask for options, name two or three short labels (a phrase each, not developed prose) and let them pick or redirect. Catch yourself the moment a response stops being a question or a restatement of *their* stated choice and starts being invented material — that's a sign you've slipped from brainstorming into drafting, which this skill exists to prevent. Exception: when extracting a baseline from a source text your human partner already supplied (see "Source-Derived Variance Check" in the Process below), paraphrasing what the source itself already does is not inventing — but it still needs their confirmation before anything gets locked in as a fixed dimension.
</HARD-GATE>

<EXTREMELY-IMPORTANT>
Do this yourself, directly in the conversation with your human partner. Never dispatch this skill (or any part of it) to a subagent via `task` — a subagent cannot ask your human partner anything and would have to fabricate every dimension's answer, producing a spec nobody actually agreed to.
</EXTREMELY-IMPORTANT>

**Announce at start:** "I'm using the story-brainstorming skill to build the dimension spec."

**Save the spec to:** `docs/psalm-saga/<slug>-spec.md`

**Reference files:** `references/writing-style.md`, `references/narrative-voice.md`, `references/character.md`, `references/plot-structure.md`, `references/scene-sequence.md`, `references/world-building.md` — one per dimension below, each with fuller definitions, examples, common pitfalls, and the literature the dimension is grounded in. Read the relevant reference file the first time you work each dimension in a session; the bullet points below are a checklist, not the full explanation.

## Process

1. **Premise.** Ask what the person is trying to write and why: audience, length, genre, what a satisfying read *feels* like when it's done. Don't skip to dimensions before the premise is clear.
2. **Derivative check.** Ask directly: is this based on, inspired by, a continuation of, or a retelling of an existing work? If yes, note it now and invoke `adapting-existing-work` after finishing Step 4 below, before presenting the spec for sign-off. Don't let "just inspired by the vibe of X" slide past this question — let your human partner decide whether that counts.
3. **Source-derived variance check.** If your human partner has supplied a source text (their own prior draft or an existing work) and wants "the same story" with only some named dimension(s) changed — e.g. same plot and world, different characters — this is a distinct mode from Step 2's legal/relationship question and can apply regardless of how that was answered:
   - Read the source text.
   - Draft baseline answers for all six dimensions as the source text actually exercises them — paraphrase, don't embellish (see the hard-gate exception above).
   - Present the full baseline to your human partner in one pass and get confirmation or edits before locking anything.
   - Lock every dimension they confirm as unchanged. Mark only the dimension(s) they named as open — those are the only ones Step 4 actually elicits; walk them normally.
   - Every answer given for an open dimension must be checked against every locked dimension per Step 4's compatibility check below — a locked "preserve the coat" is not safe just because it's locked, if the open Character dimension just made coats physically implausible.
4. **Walk the six dimensions, one at a time**, presenting each in a short chunk your human partner can actually read and react to (per-dimension, not all thirty-six sub-dimensions dumped at once). Read that dimension's reference file before asking its questions if this is the first time in the session you're covering it. For each dimension, ask about its sub-dimensions and write down the concrete choice, not a vague aspiration ("wry, understated" beats "funny"). (In source-derived variance mode, only the dimension(s) marked open in Step 3 get walked — everything else is already locked.)
   - **Carry constraints forward.** Before asking a dimension's questions, restate whichever choices already on record plausibly constrain it (e.g., opening World-Building by noting what Character already established about the protagonist's species, scale, or environment). This includes both dimensions answered earlier in this walk and anything locked in Step 3.
   - **Stop on contradiction.** If a new answer contradicts a restated constraint — or contradicts a locked dimension from Step 3 — don't silently accept it and don't silently resolve it yourself. Name the contradiction plainly and ask your human partner which side to revise.

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

5. **Cross-dimension consistency pass.** Once every dimension (open or locked) has an answer, re-read the full draft spec as a whole — not dimension-by-dimension — before writing or showing it. Check the pairs that clash most often in practice: Character against World-Building's material/behavioural detail, Character against Plot's physical feasibility, World-Building's rules against Plot's events, and **Character's communication modality (does it speak, how, how much) against Narrative Voice's focalisation/interiority-access and Writing Style's discourse organisation and rhetorical patterns** — a Character answer that grants fuller or different communication than the source used (e.g. "understandable communication" for a species that was wordless in the source) will otherwise silently license a different discourse form later, one dimension at a time, without ever reading as a single contradiction. Pin down concretely what the communication choice does and doesn't permit (dialogue vs. gesture vs. inferred meaning) rather than leaving it as an adjective. Surface anything you find the same way as an inline contradiction in Step 4 — name it, ask which side to revise — rather than quietly editing the spec yourself.
6. **Write the spec** to `docs/psalm-saga/<slug>-spec.md` with one section per dimension, each sub-dimension as a bullet with the agreed choice in the human partner's own words wherever possible. Head the file with a one-line note that these sections mirror PSALM §3.3.
7. **Get explicit sign-off** before invoking `adapting-existing-work` (if flagged in step 2) or `writing-story-plans`. Show the spec, don't assume silence is approval.

## Red Flags

| Thought | Reality |
|---------|---------|
| "I'll just start writing, style will emerge naturally" | It will — inconsistently. Decide it now so `reviewing-story-dimensions` has something to check against. |
| "The character function is obviously 'protagonist', skip it" | Fine to answer briefly, but still write it down — don't silently drop a dimension. |
| "This dimension doesn't apply to this story" | Rare, but possible (e.g. a plotless mood piece may have thin Plot Structure). Say so explicitly in the spec rather than leaving the section blank. |
| "The person just wants a quick draft, skip the spec" | Ceremony scales down, not to zero — even a quick draft benefits from one sentence per dimension, and it's the cheapest possible insurance against a story that reads like nothing was decided. |
| "I'll sketch a bit of lore/a sample scene so they have something concrete to react to" | That's drafting wearing a brainstorming costume. A sketch anchors *your* invented details in their spec instead of theirs — ask a sharper question instead of writing the illustration yourself. |
| "I've read the dimension list before, I don't need the reference file again" | Fine to skip on repeat sessions once you've internalised it — but the first time through each dimension in a session, read the reference; the bullets alone under-specify concepts like focalisation vs. point of view that are easy to conflate. |
| "This detail belongs to World-Building, not my problem while I'm on Character" | Dimensions aren't independent — a Character answer can make an already-locked World-Building or Plot detail impossible (a wild animal in tailored clothing, a duel in a world that just banned weapons). Check it, don't wait for Step 5 to catch what a moment's thought would have caught here. |
| "The source already establishes this, no need to re-check it" | A locked/unchanged dimension is only safe until something else changes underneath it. Re-run the compatibility check whenever an open dimension's answer could touch it, even if the locked value itself never gets re-asked. |

## Autonomous Mode

Only active when `batch-story-generation` is the force-injected bootstrap
for this session (a `psalm-saga-batch` run). In every other session,
ignore this section — the hard gates above (ask, don't propose; get
explicit sign-off) are the only rule you follow.

**Save path override:** save the spec to
`docs/drafts/<story_name>/<story_name>-spec.md` instead of
`docs/psalm-saga/<slug>-spec.md` — `story_name` is this story's own
kebab-case slug (see `batch-story-generation`'s naming convention),
consistent across its spec, plan, and chapter files.

**Decide, don't ask.** Every dimension question in the Process above still
gets answered — concretely, not vaguely — but you answer it yourself.
Which input mode you're working from changes what you're answering *from*:

- **Scratch:** invent the premise and all six dimensions freely. Read
  `docs/drafts/_batch-log.md` first (see `batch-story-generation`) and
  reroll before locking anything that reads as a near-duplicate of an
  already-logged story.
- **Context:** the CLI gives you one or more inspiration texts (inline or
  from files). Read them for premise-grounding only — they don't fix any
  dimension by themselves; every dimension is still yours to decide,
  informed by that material.
- **Template:** the CLI gives you one or more template documents. Each one
  states some dimensions explicitly (or partially) and leaves the rest
  unstated. Keep every explicitly-templated answer exactly as given; for
  whatever's left unstated, decide it yourself, staying consistent with
  what the template already committed to.
- **Variant:** the CLI names one source file and the specific dimension(s)
  to change for it (from the run's variant manifest). Follow the
  Source-Derived Variance Check in the Process above exactly, with one
  change: skip "present the baseline to your human partner and get
  confirmation or edits" — draft the baseline faithfully from the source
  and lock it immediately. Only the manifest-named dimension(s) get
  freshly decided; walk those the normal way, just deciding instead of
  asking.

**Self-approve instead of getting sign-off.** Still run the
cross-dimension consistency pass (Step 5) in full. If you find a
contradiction, resolve it yourself and say so in the spec's own text (e.g.
"World-Building's material detail was narrowed from X to Y to stay
consistent with Character's Z") rather than stopping to ask which side to
revise. Once the spec is internally consistent, treat it as signed off and
move straight to `writing-story-plans` (its own Autonomous Mode section).

## Handoff

End by stating explicitly: "Spec complete. [Invoking adapting-existing-work next. / Ready for writing-story-plans.]"
