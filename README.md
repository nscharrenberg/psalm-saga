# PSALM-SAGA

Synthetic story generation, built on [LangChain's `deepagents`](https://github.com/langchain-ai/deepagents).

PSALM-SAGA generates stories in two modes:

- **`from_scratch`** — brainstorm a story with the user, dimension by dimension, then write it.
  The goal is a story that is original and detailed enough that it doesn't rely on parody,
  pastiche, quotation, or genre stock elements (scenes à faire) in place of real invention, and
  doesn't read as an existing, identifiable work with the names changed.
- **`from_source`** — extract the same dimensions from an existing source text, negotiate with
  the user which dimensions to hold close vs. deliberately diverge from (a graded intensity per
  dimension, not just a yes/no), then write a new story against that plan. This mode exists to
  produce texts for evaluating a source against a generated counterpart — e.g. with
  [PSALM](https://github.com/nscharrenberg/psalm), whose narratological dimension taxonomy
  (writing style, narrative voice, characterisation, plot architecture, scene, world-building)
  this library reuses generatively rather than for similarity scoring. `saga batch` (below) uses
  this mode non-interactively to generate labeled benchmarking datasets at scale.

Both modes converge on the same shared artifact, the **Story Bible** (`story_bible.json`), and
the same writer/editor subagents — see [`docs/design.md`](docs/design.md) for the full
architecture writeup.

## Status

This is an initial implementation. It has been built and unit-tested for the parts that don't
require live model calls (the `StoryBible` schema, session lifecycle, and the deterministic
bible-validation tool). The agent graph itself (`agents/orchestrator.py`, the five subagents, and
the `ask_human` interrupt/resume flow) is implemented against the documented `deepagents` /
`langgraph` APIs but has **not** been exercised end-to-end against a live model in this
environment (no network access here to install `deepagents`/`langchain`/etc. or call a
provider). Before relying on it: `uv sync`, set a model, and run a `saga new` session yourself.

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
uv run psalm-saga new --source ./my-novel-excerpt.txt --context "Keep the voice close, vary the ending."

# Resume a session (answers a pending question, or lets you send a new message)
uv run psalm-saga resume 20260727-141203-a1b2c3
```

### Generating a PSALM benchmarking dataset

`saga batch` runs the from_source pipeline non-interactively over a whole directory of source
texts, generating one story per (source, dimension) pair with a *graded, pre-set* divergence
plan — no questions asked, so it can run unattended. The default strategy,
`isolate_preserve`, holds **one** PSALM dimension `close` to the source while holding every other
dimension `divergent`, per variant:

```bash
uv run saga batch ./source-texts/ --output ./dataset/manifest.json
```

For each `my-story.txt` in `./source-texts/`, this produces one session per dimension
(`my-story__isolate_characters`, `my-story__isolate_plot`, ...) plus `baseline_all_close` and
`baseline_all_divergent`, and a manifest (`manifest.json` + `manifest.csv`) recording, per item:
the **intended** similarity level per dimension (the label), the **achieved** level the editor
subagent assessed from the actual finished text, and any fidelity mismatches between the two.

Feeding each `(source.txt, final_story.md)` pair into PSALM and checking whether its per-dimension
scores line up with `intended` (not just `achieved`, which can itself be wrong -- see fidelity
mismatches below) is the actual benchmark: for the `isolate_characters` item, PSALM should flag
characterisation similarity and *not* plot/world-building/etc. similarity, since those were
deliberately varied.

Preview a matrix without generating anything:

```bash
uv run saga isolation-matrix --dimensions characters,plot
```

Other options worth knowing about (`uv run saga batch --help` for the rest):
- `--strategy isolate_vary` inverts the test: vary **one** dimension, hold the rest close --
  useful for checking whether a detector still fires when only one thing changed, rather than
  testing per-dimension sensitivity.
- `--near`/`--far` change the intensity levels used (default `close`/`divergent`; e.g.
  `--near identical` for an even harder positive-control point).
- `--overwrite` regenerates items whose session directory already exists; without it, a batch
  run is safe to re-invoke after a partial failure -- already-generated items are reused.
- A single one-off variant (rather than the whole matrix) can be run through `saga new` directly
  with `--divergence-plan path/to/plan.json` (a `{"characters": "close", "plot": "divergent",
  ...}` file covering all six dimensions) — this implies `--non-interactive`.

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
scènes à faire) and general resemblance to identifiable works, in a bounded revise/re-check loop
— **not** a legal compliance guarantee. No automated tool can certify originality or copyright
non-infringement; review flagged output yourself, especially in `warn` strictness mode where
generation proceeds with concerns merely noted.
