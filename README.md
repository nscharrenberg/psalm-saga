# PSALM-SAGA

Synthetic story generation, built on [LangChain's `deepagents`](https://github.com/langchain-ai/deepagents).

PSALM-SAGA generates stories in two modes:

- **`from_scratch`** — brainstorm a story with the user, dimension by dimension, then write it.
  The goal is a story that is original and detailed enough that it doesn't rely on parody,
  pastiche, quotation, or genre stock elements (scenes à faire) in place of real invention, and
  doesn't read as an existing, identifiable work with the names changed.
- **`from_source`** — extract the same dimensions from an existing source text, negotiate with
  the user which dimensions to preserve vs. deliberately vary, then write a new story against
  that plan. This mode exists to produce texts for evaluating a source against a generated
  counterpart — e.g. with [PSALM](https://github.com/nscharrenberg/psalm), whose narratological
  dimension taxonomy (writing style, narrative voice, characterisation, plot architecture, scene,
  world-building) this library reuses generatively rather than for similarity scoring.

Both modes converge on the same shared artifact, the **Story Bible** (`story_bible.json`), and
the same writer/editor subagents — see [`docs/design.md`](docs/design.md) for the full
architecture writeup.

## Status

This is an initial implementation, built and unit-tested for the parts that don't require live
model calls (the `StoryBible` schema, session lifecycle, and the deterministic bible-validation
tool). The agent graph itself (`agents/orchestrator.py`, the five subagents, and the `ask_human`
interrupt/resume flow) is implemented against the documented `deepagents`/`langgraph` APIs but
has not yet been exercised end-to-end against a live model. Before relying on it: `uv sync`, set
a model, and run a `saga new` session yourself.

## Install

Requires Python 3.14 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                     # base install
uv sync --extra anthropic   # + langchain-anthropic
uv sync --extra openai      # + langchain-openai
uv sync --extra all         # both
```

## Configure

PSALM-SAGA is provider-agnostic: pass a `provider:model` string (anything
[`init_chat_model`](https://reference.langchain.com/python/langchain/chat_models/init_chat_model)
accepts) via `--model`, or set it once via environment:

```bash
export PSALM_SAGA_MODEL="anthropic:claude-opus-4-8"
# optional:
export PSALM_SAGA_SUBAGENT_MODEL="anthropic:claude-sonnet-5"   # cheaper model for subagents
export PSALM_SAGA_SESSIONS_ROOT="./psalm-saga-sessions"
export PSALM_SAGA_ORIGINALITY_GUARD_STRICTNESS="warn"           # or "block"
export ANTHROPIC_API_KEY="..."                                  # or OPENAI_API_KEY, etc.
```

(A `.env` file in the working directory is also picked up automatically.)

## Use

```bash
# From scratch, with a seed idea
uv run psalm-saga new --context "A lighthouse keeper who starts receiving mail from ships that never made it to port."

# From scratch, no seed at all -- the brainstorm subagent starts from nothing
uv run psalm-saga new

# From a source text
uv run psalm-saga new --source ./my-novel-excerpt.txt --context "Preserve the voice, vary the ending."

# Resume a session (answers a pending question, or lets you send a new message)
uv run psalm-saga resume 20260727-141203-a1b2c3
```

Each session is a plain directory under `--sessions-root` (default `./psalm-saga-sessions/`):

```
psalm-saga-sessions/<session-id>/
    session_config.json
    psalm_dimensions_reference.md
    story_bible.json      # the shared brief every agent reads/writes
    source.txt             # from_source mode only
    draft.md
    final_story.md
    checkpoints.sqlite      # lets `saga resume` continue a paused conversation
```

## Library usage

The CLI is a thin driver around a reusable core — `session.py` + `agents/build_orchestrator` —
so the same pieces can back a web app later; only the `ask_human` transport (blocking terminal
prompts in `cli.py`) would need replacing with e.g. a websocket-backed pending-question store.

```python
from psalm_saga.config import Settings
from psalm_saga.dimensions import GenerationMode
from psalm_saga.session import init_session, checkpoint_db_path
from psalm_saga.agents import build_orchestrator
from langgraph.checkpoint.sqlite import SqliteSaver

settings = Settings(model="anthropic:claude-opus-4-8")
session_dir = init_session(settings, GenerationMode.FROM_SCRATCH, initial_context="a heist on the moon")

with SqliteSaver.from_conn_string(str(checkpoint_db_path(session_dir))) as checkpointer:
    orchestrator = build_orchestrator(settings, session_dir, checkpointer)
    # orchestrator.invoke(...) / .stream(...) as any LangGraph graph
```

## Development

```bash
uv sync   # dev dependency group is installed by default
uv run pytest
uv run ruff check .
uv run mypy src
```

## Copyright note

The `from_scratch` originality guard is a diligence aid — a subagent that critiques the story
bible against PSALM's four statutory-exception categories (parody, pastiche, quotation,
scènes à faire) and general resemblance to identifiable works — **not** a legal compliance
guarantee. No automated tool can certify originality or copyright non-infringement; review
flagged output yourself.
