# Length and Chapter Count — reference

Read this in `story-brainstorming` Step 1 the first time a story's length
comes up in a session, and again in `writing-story-plans` Step 2 when
deciding a chapter count in "auto" mode. It has two parts: the length
taxonomy `--length` resolves against, and the chapter-count heuristic — a
set of stylistic norms to weigh, not a formula to apply mechanically.

## Length Taxonomy

| Category | Range (words) |
|---|---|
| Drabble | exactly 100 |
| Flash Fiction | 1–999 |
| Short Story | 1,000–7,499 |
| Novelette | 7,500–17,499 |
| Novella | 17,500–39,999 |
| Novel | 40,000–149,999 (typically 50,000–110,000; literary/commercial fiction often lands 70,000–90,000) |
| Epic / Doorstopper | loosely, well north of 150,000 |

A session's `--length` flag (or a length mentioned in conversation, for an
interactive session with no flag) resolves to one of these categories, or
to a custom word count/range that doesn't name a category at all — either
way, the target this reference informs is the same: a word count or range
to write toward.

## Chapter Count Guidance

Chapters are a formatting and pacing choice layered on top of the word
count, not something every story needs. Use the resolved length target as
the primary signal:

- **Drabble, Flash Fiction, Short Story, Novelette**: no formal chapters.
  Continuous prose, optionally broken by a few scene dividers for a pacing
  beat — never numbered or titled chapters at these lengths.
- **Novella**: a genuine judgment call based on pacing. Often has no
  chapters at all; when it does, it's usually just a handful — roughly 3
  to 10.
- **Novel**: the first length where chapters become a real convention —
  but still no fixed rule. A novel could be 5 long chapters or 80 short
  ones. Where an author does chapter it, roughly 1,500–5,000 words per
  chapter is a common stylistic norm worth considering, not a
  requirement — plenty of successful novels ignore it entirely (some
  authors write 800-word chapters, others 10,000-word ones).
- **Epic / Doorstopper**: essentially always chaptered at this length.
  Start from the Novel guidance above and the resolved word target.

When chapter count is "auto" (no explicit `--chapters` value), decide it
using this guidance and the resolved word target, and record the
reasoning in one line in the plan — e.g. "Chapter count: 6 — auto,
~4,000 words/chapter target for this ~25,000-word novel."
