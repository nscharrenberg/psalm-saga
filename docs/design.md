# PSALM-SAGA design

## Why PSALM's dimensions, inverted

[PSALM](https://github.com/nscharrenberg/psalm) is an LLM-as-judge framework that scores
narrative *similarity* between two texts across ten evaluators grounded in EU copyright doctrine
and narratology: stylistic dimensions (writing style, narrative voice), content dimensions
(characterisation, plot architecture, scene, world-building), computational overlap, and four
statutory-exception evaluators (parody/satire, pastiche, quotation/citation, scènes à faire).

PSALM-SAGA reuses the stylistic and content dimensions as a **generative checklist** instead of a
similarity rubric: a `StoryBible` (`dimensions.py`) with one section per dimension, filled in by
agents through brainstorming or extraction, and used to drive prose generation. The four
statutory-exception categories become a **guardrail** for `from_scratch` mode (the story should
not trip any of them with respect to an identifiable existing work) and are simply irrelevant to
`from_source` mode, where controlled closeness to the source is the point.

Keeping the schema dimension-for-dimension aligned with PSALM's evaluators is what makes
`from_source` output directly usable as an evaluation counterpart in PSALM-based studies: the
`divergence_plan` records, per dimension, what was *intended* (preserve vs. vary), so a later
PSALM score can be read against stated intent.

## Two pipelines, one spine

```
from_scratch:  brainstorm ──► originality_guard ──(revise loop)──► writer ──► editor
from_source:   extract ──► brainstorm (negotiate divergence_plan) ──────────► writer ──► editor
```

Both pipelines converge on the same `writer`/`editor` subagents and the same bible schema. The
orchestrator (`agents/orchestrator.py`, prompted by `prompts/orchestrator.md`) is the only thing
that knows which pipeline it's running; individual subagents don't need to.

## deepagents mapping

| Concept | Implementation |
|---|---|
| Shared artifact | `story_bible.json` on a real filesystem backend rooted at the session dir |
| Context isolation | Each pipeline stage is a declarative `SubAgent` (`agents/subagents.py`), invoked via deepagents' built-in `task` tool |
| Forced reflection | A plain `think` tool (`tools/think.py`), à la `open_deep_research`'s `think_tool` |
| Human-in-the-loop | `ask_human` (`tools/ask_human.py`) built on `langgraph.types.interrupt`; the CLI (`cli.py`) is the only piece that knows how to *drive* the interrupt (blocking prompt today, would be a websocket/store tomorrow) |
| Self-correction | `validate_story_bible` (`tools/bible.py`), a deterministic (non-LLM) Pydantic-validation tool bound per-session |
| Resumability | A `SqliteSaver` checkpointer per session, so a paused `ask_human` question survives the CLI process exiting |
| File tools | Not reimplemented — `FilesystemMiddleware`'s built-in `ls`/`read_file`/`write_file`/`edit_file`/`glob`/`grep`, attached automatically by `create_deep_agent`/subagent defaults |

## Why not force the questionnaire through a fixed script

The brainstorm subagent decides what to ask next (conversational, one question at a time) rather
than working through a fixed list, because dimensions interact: genre and premise usually need
to be settled before scene-level sensory detail is worth asking about, and a user's answer to one
question often makes several other planned questions moot. `psalm_dimensions_reference.md`
(copied into every session directory) is the shared checklist all agents work from, but it's a
reference, not a script.

## Known limitations

- The originality guard is a diligence aid, not a legal compliance guarantee (see README).
- `warn` vs `block` strictness is enforced by a deterministic tool, `check_originality_gate`
  (`tools/gate.py`), which the orchestrator's prompt requires calling before delegating to
  `writer-agent`. It computes PROCEED/BLOCKED purely from `story_bible.json`'s
  `originality_findings` and the configured strictness -- not from the model's own judgment of
  its findings -- so the model only needs to call one tool and respect a literal string result,
  rather than reason correctly about counts and severities itself. This is *not* a graph-level
  hard veto: deepagents doesn't expose a clean hook to block a specific subagent name from
  outside the graph without subclassing `SubAgentMiddleware`/the `task` tool internals, so a
  model that ignores its instructions could still call `task(subagent="writer-agent", ...)`
  after a BLOCKED verdict. If this needs to be a true invariant rather than a much-smaller-surface
  instruction, the next step is custom middleware that intercepts `task` calls and consults the
  gate itself.
- No automated test exercises the live agent graph (would require a real or fake chat model and
  network access); `tests/` covers the schema, session lifecycle, and the deterministic
  validation tool, which are the parts safe to unit test without a model in the loop.


Note: This document was generated using Claude Sonnet 5 based on the codebase. The general design is correct, but small details may be off.Z