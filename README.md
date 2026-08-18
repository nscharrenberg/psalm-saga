# psalm-saga

A spec-first story-writing agent for the terminal, built on [LangChain Deep
Agents](https://github.com/langchain-ai/deepagents) and grounded in
**PSALM** (Scharrenberg & Sun, *Probing Stylistic Appropriation using Large
Language Models*).

Before writing a single line of prose, psalm-saga walks you through the six
expressive dimensions PSALM uses to evaluate stylistic and structural
similarity between texts: writing style, narrative voice, character, plot
structure, scene sequence, and world-building. If your story is based on an
existing work, it also walks through the four statutory-defence dimensions
PSALM evaluates (parody/satire, pastiche, quotation/citation, scènes à
faire).

The result is a written spec you sign off on, a plan that carries that spec
into concrete chapters, chapters drafted against that plan, and a review
pass that checks each chapter against the plan's own stated commitments.

## Features

- **Structured brainstorming.** Instead of one open-ended "tell me about
  your story" prompt, every dimension and sub-dimension gets elicited
  explicitly, backed by reference material from the narratology,
  stylometry, and legal literature each one is grounded in.
- **Session-based persistence.** Every conversation lives in its own
  directory with its own SQLite-backed history, and resumes exactly where
  it left off after restarting the CLI.
- **Multi-line input.** Structure your answers with lists, headings, and
  paragraphs instead of being limited to a single line per message.
- **Subagent-isolated drafting.** Chapters are drafted by an isolated
  writer subagent with exactly the context it needs, then checked against
  the spec by a separate reviewer subagent.
- **Model-agnostic.** Works with any provider LangChain's `init_chat_model`
  supports, including OpenAI's reasoning models via the Responses API.
- **Usable outside the CLI.** The skills are plain `SKILL.md` files
  following the Agent Skills spec, so they work in Claude Code or any other
  harness that reads that format.

## Installation

This project is managed with [`uv`](https://docs.astral.sh/uv/). From a
clone:

```bash
git clone https://github.com/nscharrenberg/psalm-saga.git
cd psalm-saga
uv sync --extra anthropic   # or --extra openai, or --all-extras for both
uv run psalm-saga
```

Without `uv`, a standard virtual environment works too:

```bash
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[anthropic]"
psalm-saga
```

Requires Python 3.14+ and a model provider API key, set however
[`init_chat_model`](https://python.langchain.com/docs/how_to/chat_models_universal_init/)
expects it: an exported environment variable, or a `.env` file in your
project directory.

## Quick start

```bash
cd your-project-directory
psalm-saga
```

```
you> Let's write a short story about a lighthouse keeper who finds a
     message in a bottle from someone who hasn't been born yet.

saga> Using story-brainstorming to build the dimension spec.
```

The agent opens with dimension questions, not prose: it walks through
Writing Style, Narrative Voice, Character, Plot Structure, Scene Sequence,
and World-Building one at a time, writes your answers to a spec file, and
only starts planning and drafting once you've signed off on it.

If your story is based on, inspired by, or a retelling of an existing
work, say so when asked. The agent will also walk through the four
defence-oriented dimensions (grounded in the CJEU's *Deckmyn* test for
parody, AG Emiliou's *Pelham II* opinion for pastiche, Article 5(3)(d)
InfoSoc for quotation, and the *scènes à faire* doctrine) before moving
on. This isn't legal advice. It puts your intended relationship to a
source on record. It doesn't determine whether a finished story infringes
anything.

## CLI reference

```
psalm-saga [--session SESSION_ID] [--list-sessions] [--model MODEL] [--no-banner] [--no-history]
```

| Flag                     | Description                                                                                                                                                                                                                        |
|--------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--session [SESSION_ID]` | Resume a specific session. If it already exists, its full conversation history is loaded and replayed before the prompt. Omit to start a new session.                                                                              |
| `--list-sessions`        | List existing sessions, oldest first, and exit.                                                                                                                                                                                    |
| `--model [MODEL]`        | Override the main-loop model for this run (e.g. `anthropic:claude-sonnet-4-6`, `openai:gpt-4o`, `openai:gpt-5.6-luna`). `PSALM_SAGA_AGENT__ORCHESTRATION_MODEL_NAME` environmental variable will be ignored when `--model` is set. |
| `--no-banner`            | Skip the startup banner. Useful when piping output.                                                                                                                                                                                |
| `--no-history`           | Don't persist *input* history to disk for this run. Conversation history is unaffected and always persists.                                                                                                                       |

In-session commands:

| Command          | Description                                     |
|------------------|-------------------------------------------------|
| `/help`          | Show available commands.                        |
| `/reset`         | End this session and start a genuinely new one. |
| `/session`       | Print the current session id.                   |
| `/exit`, `/quit` | End the session. Ctrl+D and Ctrl+C also work.   |

**Input:** `Enter` sends your message. `Ctrl+J` (or `Alt+Enter`) inserts a
new line without sending. Use it for lists or Markdown-structured
answers:

```
### Point 1
explanation of point 1

### Point 2
explanation of point 2
```

## Sessions

Every run works within one session: its own directory under your
project's backend root, holding its own SQLite database of the full
conversation state and its own copy of every spec, plan, and chapter file
the skills produce:

```
<root_dir>/
  sessions/
    <session-id>/
      checkpoints.sqlite      # full conversation state
      docs/psalm-saga/*.md    # this session's spec and plan
      ...                     # this session's chapter files
```

Sessions never share a directory, so multiple stories in the same project
never collide. Session ids are UUIDv7: their leading bits encode a
millisecond timestamp, so the id itself sorts in creation order. No
separate timestamp is needed in the directory name, and `ls sessions/`
lists sessions oldest to newest.

## The workflow

| Skill                        | Role                                                                                  | PSALM correspondence                                                    |
|------------------------------|---------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| `using-psalm-saga`           | Bootstrap enforcing spec before plan, plan before prose, prose before review          | —                                                                       |
| `story-brainstorming`        | Elicits explicit choices for all six dimensions and their sub-dimensions into a spec  | §3.3 infringement-oriented evaluators                                   |
| `adapting-existing-work`     | Elicits the intended relationship to a source, when the story is based on one         | §3.4 defence-oriented evaluators                                        |
| `writing-story-plans`        | Carries the spec's choices into a whole-story plan and per-chapter briefs             | —                                                                       |
| `drafting-chapters`          | Dispatches an isolated writer subagent per chapter, with a coverage review after each | —                                                                       |
| `reviewing-story-dimensions` | Checks a chapter or the whole story against its own spec and plan                     | Uses PSALM's dimension vocabulary; does not reimplement PSALM's scoring |

`story-brainstorming` and `adapting-existing-work` each carry a reference
directory of working definitions, worked examples, common pitfalls, and
grounding literature: Genette's narratology for narrative voice;
Stamatatos, Juola, and Hoover's stylometry for writing style; Palmer's
cognitive narratology for character; McKee and Bordwell & Thompson for
plot structure and scene sequence; Wolf, Ekman, and Gavins for
world-building. For adaptations: the CJEU case law and Directive articles
behind each defence.

**psalm-saga is not a PSALM reimplementation.** PSALM measures similarity
between two texts (a generated story and a named source). `reviewing-story-dimensions` checks one text against its own
stated spec: a coverage checklist, not a similarity score. For an actual
PSALM run (auditing an adaptation's similarity to its declared source, or
checking for unintended stylistic appropriation), use the PSALM framework
itself. This project only makes sure the dimensions were decided on
purpose before any prose got written.

The skills are plain `SKILL.md` files following the Agent Skills spec, so
they're usable outside this CLI too:

```bash
python -c "from psalm_saga import SKILLS_DIR; print(SKILLS_DIR)"
cp -r "$(python -c 'from psalm_saga import SKILLS_DIR; print(SKILLS_DIR)')" .claude/skills/psalm-saga
```

## Configuration

Settings are environment variables prefixed `PSALM_SAGA_`, with `__` as
the nested-field delimiter, loaded from a `.env` file in your project
directory if present.

```bash
# Model driving the main conversation loop
PSALM_SAGA_AGENT__ORCHESTRATION_MODEL_NAME=anthropic:claude-sonnet-4-6

# Model driving the chapter-writer and dimension-reviewer subagents
PSALM_SAGA_AGENT__SUBAGENT_MODEL_NAME=anthropic:claude-sonnet-4-6

# Where sessions are stored (defaults to the current directory)
PSALM_SAGA_BACKEND__ROOT_DIR=./my-story

# Give the agent unsandboxed local shell access (off by default)
PSALM_SAGA_BACKEND__ENABLE_SHELL=false
```

### OpenAI reasoning models

GPT-5-family reasoning models (`gpt-5`, `gpt-5.1`–`5.x`, the o-series)
reject `reasoning_effort` together with function tools on the Chat
Completions API, which this agent always uses. Route through the
Responses API instead:

```bash
PSALM_SAGA_AGENT__MODEL_KWARGS={"use_responses_api": true}
PSALM_SAGA_AGENT__SUBAGENT_MODEL_KWARGS={"use_responses_api": true}
```

`model_kwargs` and `subagent_model_kwargs` are forwarded as-is to
`init_chat_model()`, so any other provider- or model-specific keyword
argument works the same way.

### Reliability

Model retries, model- and tool-call limits, and rate limiting are all
configurable and enabled by default. See `psalm_saga/settings.py` for the
full set of fields (`RateLimiterSettings`, `ModelRetrySettings`,
`ModelCallLimitSettings`, `ToolCallLimitSettings`).

Model provider credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
are read the normal way each provider's SDK expects.

## Using it programmatically

```python
from psalm_saga import build_agent, Settings
from psalm_saga.agent import open_sqlite_checkpointer
from psalm_saga.session import generate_session_id

settings = Settings()
session_id = generate_session_id()

with open_sqlite_checkpointer(settings, session_id) as checkpointer:
    agent = build_agent(settings, session_id=session_id, checkpointer=checkpointer)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Let's write a short story about a lighthouse keeper"}]},
        config={"configurable": {"thread_id": session_id}},
    )
    print(result["messages"][-1].content)
```

For a one-off run with no persistence needed:

```python
agent = build_agent(Settings())  # ephemeral session, in-memory state
```

`build_agent` wires up:

- The skills, mounted at a fixed virtual backend route independent of
  wherever your project files live.
- A session-scoped project-files backend: every file a skill writes lands
  under that session's own directory.
- The `using-psalm-saga` bootstrap, force-injected into the system prompt
  on every turn.
- The `chapter-writer` and `dimension-reviewer` named subagents, each with
  an independent model.
- Todo tracking, and the reliability middleware described above.
- A checkpointer: in-memory by default, or whatever you pass in. The CLI
  always passes a persistent `SqliteSaver`.

## Roadmap

- **Non-interactive mode for batch generation.** A scriptable entry point
  that runs a full brainstorm-to-draft pipeline from a pre-filled spec
  instead of an interactive session, for generating many stories under
  controlled conditions without manual involvement in each one.
- **Experiments and evaluation infrastructure.** Tooling for running
  generation at scale under varied conditions (models, dimension
  combinations, source materials) and collecting results systematically,
  as a companion to the single-session interactive workflow.
- **Prompt improvements:**
    - **Dimension matrix support:** a structured, machine-readable
      representation of dimension choices and their relative weighting,
      alongside the current free-text spec, closer to how PSALM itself
      aggregates weighted sub-dimensions.
    - **Web search:** a research tool available during brainstorming and
      planning, for grounding a story's setting, period, or subject matter
      in verifiable detail rather than the model's unaided recall.
    - **Retrieval-augmented generation (or MCP) for adaptations:** when a story is
      based on an existing work, retrieving actual excerpts from that source
      during drafting, so `adapting-existing-work`'s dimension choices are
      checked against real text rather than the model's paraphrase of it.
- **The PSALM evaluation framework as a safeguard.** Wiring PSALM's
  evaluators in as a post-hoc audit step: scoring a finished
  story against its declared source, so this project's dimension spec and
  PSALM's own scoring check each other.
- **A web interface.** A browser-based alternative to the terminal CLI for
  demonstrations and non-technical use.

## Development

```bash
git clone https://github.com/nscharrenberg/psalm-saga.git
cd psalm-saga
uv sync --group dev
uv run pytest
```

Linting and type checking use `ruff` and `mypy`, configured in
`pyproject.toml`:

```bash
uv run ruff check .
uv run mypy psalm_saga
```