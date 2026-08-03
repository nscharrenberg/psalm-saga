# Structured choices for `ask_human`

## Problem

`psalm-saga new` asks the user questions through a single tool, `ask_human`
(`src/psalm_saga/tools/ask_human.py`), which takes a `question` and optional `why` and always
resolves to a plain free-text prompt in the CLI (`_prompt_for_interrupt` in `cli.py`, backed by
`rich.prompt.Prompt.ask`). `brainstorm.md` already coaches the agent to lead with concrete,
vivid proposals ("what if the rival is a harbor official, or his own daughter...") rather than
abstract questions, but even a proposal like that still lands as a wall of text the user has to
answer by typing a reply from scratch.

This spec adds a selectable-options interface to `ask_human`, closer to how Claude Code presents
multiple-choice questions: the agent can offer 2-4 concrete directions as a menu, with the user
always also able to write a free-text answer or say they want to discuss the question further
before deciding.

## Non-goals

- No change to `resume`'s "no pending question, what do you want to say" free-text follow-up
  flow — that's the user proactively messaging the agent, not answering a structured question.
- No change to non-interactive/batch sessions (`batch.py`) — `ask_human` short-circuits before
  any of this logic runs when `non_interactive=True`.
- No new persistence format. Everything here rides on the existing `interrupt()` /
  `Command(resume=...)` mechanism and the existing session checkpoint files.

## Design

### `ask_human` tool contract

Add one new optional parameter to the tool in `tools/ask_human.py`:

```python
def ask_human(question: str, options: list[str] | None = None, why: str = "") -> str
```

- `options`: an optional list of 2-4 short, concrete, mutually exclusive directions the user can
  pick from (e.g. `["A harbor official who wants the letters stopped", "His own daughter,
  scared of what he's becoming"]`). The agent supplies this whenever it has specific proposals in
  mind — per `brainstorm.md`'s existing "lead with a vivid proposal" style, this is most of the
  time. Left unset, the question stays fully open/free-text, unchanged from today.
- The agent should **not** add its own "something else" / "let me think" filler option — the CLI
  always appends those automatically (see below), so the agent's list should only contain
  substantive proposals.
- When set, `options` is added to the `interrupt()` payload as `payload["options"]`, alongside
  the existing `question` and (optional) `why` keys.
- The tool's docstring is updated to document `options` and to explain the `STILL_EXPLORING`
  reply convention (below), so the agent knows how to interpret what comes back.

### CLI rendering (`_prompt_for_interrupt` in `cli.py`)

- If the interrupt payload has no `options` key (or it's empty/absent, including on old
  checkpoints written before this change): render exactly as today — a `Panel` with the
  question/why, then `Prompt.ask` for free text.
- If `options` is present: after the same `Panel`, render an arrow-key selectable menu via a new
  dependency, **`questionary`** (`questionary.select`, built on `prompt_toolkit`), with choices:
  1. each of the agent's `options`, in order,
  2. `"Write my own answer..."`,
  3. `"Let's talk about it more"`.

  `questionary` is added to `pyproject.toml` as a base dependency (not optional) since it's
  needed by the core interactive CLI flow.

- Resolving the selection, and what gets sent back via `Command(resume=...)`:
  - **One of the agent's options** → resume with that option's exact text. This is
    indistinguishable from the user typing that exact string themselves, so nothing downstream
    of `ask_human`'s return value (bible updates, subagent prompts) needs to change.
  - **"Write my own answer..."** → prompt free text (`Prompt.ask`, same as today's flow), resume
    with it verbatim.
  - **"Let's talk about it more"** → prompt free text with a different label ("What's on your
    mind?"), then wrap it with a fixed prefix before resuming (see below) so the agent can tell
    this reply apart from a settled answer.
  - **Ctrl-C / cancelled menu** (`questionary` returns `None`) → exit the CLI cleanly
    (`typer.Exit(code=1)`), same spirit as any other user-initiated abort.

### The "still discussing" convention

`ask_human`'s return type stays a plain string (it's fed back into the graph as tool output), so
"this isn't a final answer" has to be signaled in-band. Mirror the pattern the codebase already
uses for `NON_INTERACTIVE_REPLY` in the same file: a constant, self-describing prefix.

```python
STILL_EXPLORING_PREFIX = (
    "STILL_EXPLORING (this is not a final answer -- the user wants to discuss this specific "
    "question further before deciding; respond conversationally and keep exploring it with "
    "them, don't record anything as settled yet): "
)

def format_discussion_reply(text: str) -> str:
    return f"{STILL_EXPLORING_PREFIX}{text}"
```

`format_discussion_reply` lives in `tools/ask_human.py` (co-located with the analogous
`NON_INTERACTIVE_REPLY`) and is imported by `cli.py` for the "Let's talk about it more" branch.

### Agent prompt changes (`prompts/brainstorm.md`)

- Under "Ground rules": pass `options` whenever there are 2-4 concrete directions in mind (most
  of the time, given the existing proposal-first style); keep each option short enough to read
  as one menu line; don't add a filler "something else" option, the user always gets that.
- Add a line on handling a `STILL_EXPLORING`-prefixed reply: treat it as a cue to keep
  discussing that specific question — ask a follow-up, riff, or offer a fresh set of options —
  rather than writing anything to `story_bible.json` for it yet.
- Update the "If invoked to negotiate a divergence plan" section: each per-dimension ask can pass
  `options=["identical", "close", "moderate", "loose", "divergent"]` alongside a `why` explaining
  the agent's proposed default for that dimension.

### Activity log (`activity.py`)

`describe_tool_call` for `ask_human` gets a small, best-effort addition: when the call includes
`options`, append a count to the existing one-line log entry, e.g.:

```
❓ asking: Which direction for the rival? (3 options)
```

Purely cosmetic; stays inside the existing broad try/except so a formatting surprise here can
never break a session.

## Error handling

- **Old checkpoints**: sessions with interrupts recorded before this change simply lack the
  `options` key; the CLI's `payload.get("options")` returns `None` and it falls back to the
  existing free-text path. No migration needed.
- **Menu cancellation**: `questionary.select(...).ask()` returning `None` (Ctrl-C) exits the CLI
  rather than crashing or looping.
- **Non-interactive sessions**: unaffected — `ask_human` returns `NON_INTERACTIVE_REPLY` before
  any interrupt/options logic runs, exactly as today.
- **Malformed `options`** (e.g. the agent passes a single-item or empty list): the CLI doesn't
  validate this — an `options` list with fewer than 2 items still renders as a (degenerate but
  functional) menu with the write-your-own/discuss-further items appended. Not worth guarding in
  the tool itself; the prompt guidance is the primary lever for good option counts, consistent
  with how the rest of the prompt-driven behavior in this codebase isn't schema-enforced.

## Testing

No live model calls required, consistent with the rest of the suite:

- `tools/ask_human.py`: unit test that `options`, when passed, ends up in the `interrupt()`
  payload; unit test that `format_discussion_reply` produces the expected prefixed string.
- `cli.py`: unit test `_prompt_for_interrupt`'s branching for (a) no `options` → unchanged
  `Prompt.ask` path, (b) `options` present + an agent option selected → resumes with that exact
  text, (c) "Write my own answer..." selected → resumes with typed text, (d) "Let's talk about
  it more" selected → resumes with the `STILL_EXPLORING`-prefixed text. Achieved by monkeypatching
  `questionary.select` and `Prompt.ask` rather than driving a real terminal.
- `activity.py`: extend the existing `test_describe_tool_call_ask_human` test to cover the
  options-count suffix when `options` are present in the call args.
