# PSALM Dimension Field Guide

This is the shared reference for the dimensions PSALM-SAGA generates against. It mirrors the
evaluator taxonomy of PSALM (github.com/nscharrenberg/psalm), a framework that scores narrative
*similarity* along these axes. PSALM-SAGA uses the same axes generatively: each one becomes a
section of `story_bible.json` to fill in.

## writing_style
Register, sentence rhythm, lexical density, figurative language, tone, dialogue style. This is
*how* the prose sounds, independent of what happens in it.

## narrative_voice
Point of view (first/second/third person; narrator knowledge: limited, multiple, omniscient,
objective), narrative distance, narrator presence, focalisation, temporal perspective, reader
engagement. This is *who* is telling the story and how close they stand to the events.

## characters
Each character's role, external goal, internal need, flaw, arc, voice, relationships, backstory.
Distinguish what a character *wants* (external goal) from what they *need* (internal need) --
the gap between the two is usually where the story's engine is.

## plot
Structure (three-act, five-act, kishotenketsu, in medias res, frame tale, ...), inciting
incident, turning points, climax, resolution, causality. Causality matters more than sequence:
"and then" is a chronicle; "and therefore" / "but" is a plot.

## scenes
Individual scenes: setting, sensory texture, dramatic function, who's present, tension. Not
every scene needs to be enumerated up front -- a handful of anchor scenes is enough for the
writer subagent to work from.

## world_building
Geography & spatial design, rules & systems (magic / technology / physics / politics / economy
and their *limits*), culture & society, history & myth.

---

## Statutory-exception categories (guardrail only -- from_scratch mode)

These are the categories PSALM's defence evaluators check for on the *judging* side. In
from_scratch generation, the goal is a story that does not read as any of these with respect to
an existing work, and is not itself simply a copy with the names changed:

- **parody / satire** -- deliberately imitates a specific work's recognisable style or content
  for comedic/critical effect
- **pastiche** -- imitates a specific work's or author's style as homage, without the critical
  distance of parody
- **quotation / citation** -- reproduces specific passages of an existing work
- **scenes a faire** -- relies on stock elements standard to a genre such that they aren't
  original expression (this one is about genre *cliche*, not about resembling one specific work)

A story can use genre conventions (a farmboy discovers he is chosen; a ship crosses a threshold
into a magical land) without violating this -- the concern is when the *combination and specific
expression* of elements traces a particular existing work rather than the genre in general.
