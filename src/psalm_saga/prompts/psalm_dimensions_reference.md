# PSALM Dimension Field Guide

This is the shared reference for the dimensions PSALM-SAGA generates against. It mirrors the
evaluator taxonomy of PSALM (github.com/nscharrenberg/psalm), a framework that scores narrative
*similarity* along these axes. PSALM-SAGA uses the same axes generatively: each one becomes a
section of `story_bible.json` to fill in.

**This is internal bookkeeping, not a script.** The dimension names and vocabulary below are for
agents to track progress and structure `story_bible.json` -- they should not leak into what gets
said to the user (see `brainstorm.md` for how to translate a dimension into an actual creative
question or proposal). All changes to `story_bible.json` go through the `update_story_bible` tool
(never `write_file`/`edit_file` on it directly, and never a different file for it), which
validates a patch before writing anything -- see `tools/bible.py`.

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

---

## Divergence intensity scale (from_source mode only)

Each PSALM dimension gets an intended (and, after editing, an achieved) similarity level relative
to the source, from most to least similar:

| Level | Meaning |
|---|---|
| `identical` | Near-verbatim reuse of this dimension's content. Rare as a real goal -- mostly an extreme test point for benchmarking a detector. |
| `close` | Same core choices as the source, varied only in surface detail. |
| `moderate` | Recognizably related to the source's treatment, but with real, substantive changes. |
| `loose` | Only faint or structural resemblance remains. |
| `divergent` | Deliberately different; no meaningful echo of the source's choices. |

This is what lets a generated story double as a labeled benchmarking item: `divergence_plan` is
the intended label, `achieved_divergence` (set by the editor subagent) is what the story actually
delivered, and `evaluate_fidelity()` flags any dimension where the two don't match.
