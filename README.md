# PSALM-SAGA v2

Turn literary texts — including copyrighted ones — into **synthetic counterparts** that keep
the research-relevant data points (structure, events, character network, narrative voice,
stylometric profile, language) and none of the protected expression (sentences, phrasing,
names, distinctive particulars). Built for giving researchers access to a library's
collection through a synthetic dataset instead of the original texts.

The same engine also writes new stories from a premise or a (partial) specification, and
ships the baselines and ablations needed to evaluate it.

```
source ──► extract ──► spec ──► transform ─┃─► plan ──► draft ──► review ──► guard ──► assemble ──► evaluate
            (map-reduce,  (per-dimension,   ┃  (outline + (chapter /  (calibrated, (verbatim   (localised   (fidelity +
             story bible)  6 × 6 sub-dims)  ┃   scenes)    scene)      targeted)    overlap)    headings)    leakage)
                                 clean-room boundary: nothing right of this line reads the source text
```

Three interfaces over one engine: a **CLI** (batch commands and an interactive session), a
**Python SDK**, and a **web app**.

---

## Install

```bash
git clone https://github.com/nscharrenberg/psalm-saga.git && cd psalm-saga
uv venv && uv pip install -e ".[all]"        # or: pip install -e ".[all]"
```

Python ≥ 3.11. Every `saga …` command can also be run as `python -m psalm_saga …`
(with uv: `uv run python -m psalm_saga serve`). Use that form if your machine blocks the
generated `saga.exe` launcher — the "Failed to spawn: `saga` … Access is denied (os error 5)"
error on managed Windows laptops.

Models are called through [LiteLLM](https://docs.litellm.ai/docs/providers), so
any provider works. Give your own keys in the web app (**API keys**, top right) or with
`saga keys set OPENAI_API_KEY`; they are kept on your computer only (`~/.psalm-saga/keys.json`,
never in run folders) and take precedence over environment variables, which also work:

| Provider | Model id example | Key |
|---|---|---|
| Anthropic | `anthropic/claude-sonnet-5-5` (default), `anthropic/claude-opus-5-5`, `anthropic/claude-haiku-5-5` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai/gpt-5.5` | `OPENAI_API_KEY` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` |
| Moonshot (Kimi) | `moonshot/kimi-k2-0905-preview` | `MOONSHOT_API_KEY` |
| Self-hosted (vLLM, Ollama, TGI) | `hosted_vllm/<model>` + `models.default.extra.api_base=http://…/v1`, `ollama/<model>` | – |
| **Offline (no model)** | `fake/anything` | – |

> **Copyrighted input and third-party APIs.** Sending in-copyright library material to an
> external API may not be permitted by the library's licences. For in-copyright runs, point
> PSALM-SAGA at a model hosted inside the library (`hosted_vllm/…` or `ollama/…`).

Model ids above are examples; check each provider's current names.

---

## Quick start

### CLI

```bash
saga run boek.txt                                   # source → synthetic counterpart (preset: full)
saga run boek.txt --until spec                      # stop after the spec to review it first
saga resume runs/<id>                               # continue (also after a crash or rate-limit storm)
saga resume runs/<id> --from plan                   # redo planning onward after editing spec.json
saga run premise.md --as premise --words 3000       # write a new story from a premise
saga run spec.json                                  # write from a (partial) specification
saga run boek.txt -p no_review -m openai/gpt-5.5 --set stages.guard.params.min_span=8
saga edit runs/<id> spec "Make the narrator intrude with ironic asides." --run
saga show runs/<id> evaluation                      # story | spec | spec_source | bible | plan | transform | chapter:N | events
saga graph runs/<id> --format graphml               # knowledge graph for Gephi / networkx
saga presets · saga stages · saga config full --set transform.policy.character=regenerate
saga chat                                           # interactive session
saga serve                                          # web app on http://127.0.0.1:8765
saga experiment experiments/pilot.yaml              # experiment grid (resumable)
```

`saga chat` works like a coding agent session for stories: `/new <file|text>`, then `/next`
builds the spec and stops; type changes in plain language ("Teun should be older and
more evasive"), `/next` plans and stops again, `/next` writes. `/show`, `/focus`, `/edit`,
`/rerun`, `/set`, `/help`.

### SDK

```python
from psalm_saga import Saga

saga = Saga("full", overrides={"models.default.name": "anthropic/claude-sonnet-5-5",
                               "limits.max_cost_usd": 5})
run = saga.synthesize(open("boek.txt", encoding="utf-8").read())
print(run.story[:400])
print(run.evaluation["fidelity"]["characters"], run.evaluation["leakage"])

run.edit("spec", "De verteller is ironischer en spreekt de lezer af en toe aan.")
run.edit("chapter_plan:3", "Move the confession to the end of the chapter.")
run.run()                                   # only invalidated stages are regenerated

draft = saga.write(premise="Een vuurtorenwachter vindt een fles met een brief uit de toekomst.")
```

Async variants: `await saga.asynthesize(...)`, `await run.arun()`, `await run.aedit(...)`.
Lower level: `psalm_saga.Pipeline.create(...)/open(...)` and `await pipeline.run(rerun_from=…, until=…, only=[…])`.

### Web app

`saga serve` → upload or paste a text, pick a preset, toggle stages, set the per-dimension
transform policy, model, language, length and budget; watch the run live in the **activity**
tab (stages as collapsible groups, chapters within them, every model call with tokens, time,
cost and the start of its answer, calls still in flight, retries and warnings — built from
the run's own `events.jsonl`, so watching does not slow the run); read and edit the spec (field by field or with an instruction), the story bible and
renames, the plan (per chapter), and chapters (revise or redraft one); inspect the
evaluation and apply one, several or all suggested fixes. Runs started from the CLI show up too.

Everything explains itself: presets, stages, policies and dimensions have plain-language
descriptions and an *i* button; clicking a stage on the run's track says what it does and what it
cost; **Help & glossary** explains the terms. The texts live in `psalm_saga/web/help.py`.

**Evaluation.** Every measure is reported as a raw value and as a **score from 0 to 1 where 1 is
best** — shares used as they are, correlations as max(0, r), differences inverted as
max(0, 1 − d / c), ratios as max(0, 1 − |x − 1| / c) — with the formula shown per measure (green
≥ 0.80, orange ≥ 0.60). Measures are grouped by question (language and form, style, structure,
characters, content, protected expression); a **core** subset is what experiments compare.

**Judges (optional).** Language-model judges are off by default and have their own settings, so
they can run on a model of a different family from the writer: `--set judges.enabled=true --set
judges.model=anthropic/claude-sonnet-5-5` (or the *Judges* section of the web form, or *Run the
judges* on a finished run's evaluation, which redoes only the evaluation). Instruments
(`judges.instruments`): `psalm` — an improved PSALM judge that compares the texts on the six
dimensions and 36 aspects, describing both, citing short evidence from each and arguing every
verdict, with *function* (does it do the same thing?) and *expression* (are the concrete
particulars the same?) rated separately; `content` — same story, from both texts' chapter
summaries; `style` — same writing, from name-masked excerpts.

**Fixes make versions.** A suggested fix copies the run to a new version (`<run>-v2`, …), applies
the fix there and redoes everything from the stage it names; the original is never changed, and
the new version's evaluation shows, per measure, the change against the version it came from.
Fixes are targeted (style and dialect by the style-matching stage alone; structure and characters
by re-planning with the *specific* design items that were missing; gender by redrafting with each
character's gender), and a version's fix instruction replaces the previous one instead of piling up.

---

## Concepts

**Modes.** *source* (a text to synthesise a counterpart of), *premise* (write new), *spec*
(write from a full or partial specification — missing dimensions are filled in, given ones
are kept verbatim). Detected from the input; force with `--as`.

**Dimensions.** The six PSALM dimensions × six sub-dimensions (writing style, narrative
voice, character, plot structure, scene sequence, world-building) in
`psalm_saga/taxonomies/psalm.yaml`. Swap the taxonomy with `taxonomy: path/to/file.yaml`.

**Transform policy** (source mode), per dimension:
`preserve` (keep the value, paraphrased — never quoted), `abstract` (keep function and
structure, re-invent the concrete realisation; sub-dimensions marked `surface` must change),
`regenerate` (invent anew, consistent with what is kept). Default: style, voice and plot
preserved; character, scene sequence and world-building abstracted; all names replaced with
culturally and period-appropriate new ones (`transform.rename_entities`,
`transform.keep_cultural_setting`).

**Language.** Output language = input language unless `language.output` is set. Every prompt
carries an explicit language directive, every chapter is language-checked and redrafted on
mismatch, and headings ("Hoofdstuk 3", "Kapitel 3") are rendered by code, never by the model.

**Language variety.** Dialect, sociolect and historical spelling are part of the writing
style, so they are kept too. Analysis names the variety (e.g. *19th-century Dutch,
De Vries–Te Winkel spelling*) and lists marker forms with their modern equivalents
(*mensch*/mens, *zoo*/zo, *gij*/jij); only markers the source actually uses are kept. The
writer is told to use the variety, every chapter is checked by counting marker forms and
redrafted if it drifted to the modern standard, and `evaluation.json` reports the share of
variety forms in source and synthetic text. `--variety modern` (or
`language.variety=modern`) produces a deliberately modernised corpus instead; any other
text describes a variety to use (`--variety "Brabants in de dialogen"`). With
`transform.policy.writing_style=regenerate` the variety is not carried over.

**Knowledge graph.** The story bible is also a graph: characters, places, objects and
organisations with their typed relations, scenes (where they are set, who appears), events
(who is involved, where, what causes what) and chapters. The web app's *bible* tab explores
it interactively — filter node and link types, restrict to a chapter range, search, focus on
a node's neighbourhood, switch between force, timeline and concentric layouts, and click any
node or link for details, including each entity's counterpart in the other text. Export it
with `saga graph runs/<id> [--source] [--format graphml|json]` (GraphML opens in Gephi, yEd,
Cytoscape or networkx) or `run.graph()` in the SDK.

**Comparing source and synthetic graphs.** *compare: source vs design* aligns the source graph
with the design the story was written from; *compare: source vs synthetic text* first
re-extracts a graph from the synthetic story with the same extractor (one extraction pass) and
shows what the text actually realises. Nodes and links are marked kept (faded), changed
(orange), only in the source (red, dashed) or only in the synthetic text (green); *Changes
only* hides everything kept, and the side panel gives recall per node and link type. CLI:
`saga graph runs/<id> --compare design|text`; SDK: `run.recover()`, `run.graph("compare",
against="text")`.

**Length.** `length.target_words` (default: match the source) and `length.chapters`
(`match` the source, `auto`, or a number). Chapter budgets follow the source's chapter
proportions; clearly short chapters are topped up by continuation.

**Run directory.** Every artifact is a readable file (`runs/<id>/spec.json`, `plan.json`,
`chapters/ch_003.json`, `story.md`, `evaluation.json`, `events.jsonl`, `run.json` with config and
token/cost usage per stage tag). Edit any of them by hand and `saga resume --from <stage>`.

---

## Presets (experimental conditions)

| Preset | What it is |
|---|---|
| `full` | C1: extract → spec → transform → plan → draft → review → guard |
| `no_review` | C2: without review/repair |
| `flat_spec` | C3: one call from the transformed spec + skeleton |
| `no_spec` | C4: no dimension spec; planned from the renamed/re-skinned skeleton only |
| `flat` | C5: one call, given the source (or premise), asked for a counterpart |
| `paraphrase` | naive synthetic-corpus baseline: rename + passage-by-passage paraphrase |
| `agents_room` | C6: Agents' Room (Huot et al., 2024) with the same inputs as C1 |
| `fast` | cheap iteration: small model for extraction/transform, no review |

Presets are YAML with `extends:`; any field can be overridden with `--set key=value` (CLI),
`overrides={...}` (SDK) or the web form. Swap one stage implementation:
`--set stages.draft.impl=agents_room`. Use different models per stage:
`--set models.review.name=openai/gpt-5.5` (roles are stage names; unspecified fields inherit
from `models.default`). Override prompts for a model family with `prompts_dir: my_prompts/`
(any `*.md` there replaces the built-in template of the same name).

### Add your own stage

```python
from psalm_saga import register, Stage

@register("draft", "my_writer")
class MyWriter(Stage):
    outputs = ("chapters/ch_*.json",)
    async def run(self, ctx):
        plan = ctx.store.read_json("plan.json")
        text = await ctx.text(self.model_role, "You are a novelist.", [...])
        ...
```

then `--set stages.draft.impl=my_writer`.

---

## Reliability and cost controls

- Per-model concurrency, requests/min and tokens/min limits (`models.<role>.max_concurrency|rpm|tpm`).
- 429s honour `Retry-After` and pause *all* calls to that model (shared cooldown); timeouts,
  5xx and connection errors are retried with jittered exponential backoff.
- Generations are streamed (no idle-connection timeouts) and continued automatically when
  they hit the output cap.
- Structured outputs are validated; invalid JSON gets a targeted repair round-trip.
- On-disk response cache (`runs/.llm_cache`): resuming or re-running is free for finished calls.
- Prompt caching: the stable prefix (spec, bible) is marked cacheable for Anthropic and
  ordered first for providers that cache automatically.
- `limits.max_cost_usd` stops a run when its budget is spent.
- **Reasoning models.** Their hidden reasoning counts against the output allowance, so a call
  sized for a 125-word poem could come back empty or cut off. For a reasoning model every call
  gets `models.<role>.reasoning_headroom` (default 8,000) tokens on top of what the visible
  answer needs; models are recognised from LiteLLM's table or from reasoning tokens in their
  first answer (force with `models.<role>.reasoning=true`). The headroom only prevents
  truncation; how much a model thinks is the provider's setting, e.g.
  `--set models.default.extra.reasoning_effort=high` (also in the web form). Every call has at
  least `min_output_tokens` (2,048), and an empty answer at the limit is retried with more room.
- **Full call logs.** Every call is kept under `calls/<id>.json`: all messages in, the answer,
  any reasoning text the provider returns, finish reason, tokens, time and cost
  (`log_calls: false` to switch off). The web app's activity tab opens them per call; release
  bundles leave them out, since prompts contain the source.

**Design checklist in drafting and review.** For every chapter, the facts the (transformed)
story bible fixes — its events, causal links, the relations between the people in it, and the
places and objects that belong to it — are given to the writer as "facts this chapter must
show", and the reviewer marks each one realised, missing or contradicted. Missing or
contradicted items become issues and are routed like any other (a missing event or cause is
major, a contradicted one a blocker; an item the plan itself left out goes back to planning).
A review repair is also rejected if it pushes the chapter's style further from the source's
measured profile than conform left it (`stages.review.params.style_slack`, default 0.05).
Coverage per chapter is in `reviews/ch_*.json` and shown in the chapters and activity tabs.

### Token, cost and time accounting

Every run records, in `run.json`, accumulated over every invocation (resumes, reruns,
failed attempts):

- `usage`: calls, cached calls, input / output / cache-read tokens, cost, retries and summed
  model time (`llm_seconds`), in total, per pipeline stage (`by_stage`) and per call tag
  (`by_tag`, e.g. `draft:ch3`, `repair:ch2r1`);
- `timing`: total wall-clock seconds, number of invocations, and per stage the wall-clock
  time over all attempts, the most recent completed attempt, attempts and completions.

Each model call is also an `llm_start` and an `llm_call` event in `events.jsonl` (the latter
with tokens, seconds, cost, finish reason and a 160-character preview of the answer). `saga status` and the web app's
**usage** tab show the per-stage table; experiments get `usage.*`, `timing.*` and
`stage.<name>.*` columns in `results.csv` and a cost-and-time-per-stage table in `report.md`.

Cost uses LiteLLM's price table unless you set prices yourself (needed for self-hosted
models, and useful to pin the prices reported in a paper):
`--set models.default.input_cost_per_mtok=3 --set models.default.output_cost_per_mtok=15`
(USD per million tokens; optional `cached_input_cost_per_mtok`). Calls with no known price
are counted as $0 and reported as `unpriced_calls`. Cache hits cost nothing; what they would
have cost is kept as `replayed_cost_usd` (`usage.cost_usd_first_run` in experiment results).

## Experiments

```bash
saga experiment experiments/pilot.yaml --dry-run    # list jobs
saga experiment experiments/pilot.yaml              # run (resumable), judge, report
```

Outputs `results.csv` (one row per run), `summary.json`, `report.md` (per-condition
means, per-stage cost, and the corpus-level instruments: rank agreement, dispersion,
analysis replication, distinguishability, classifier transfer, Cosine Delta attribution) and
`judgements.json`, and `report.html`: for every property, the distribution across books on the originals and on
the synthetic texts side by side (the web app links it under *Experiments*). Corpus-level analyses need a metadata CSV and are declared in the plan
(`metadata`, `analyses`, `tstr_label`; see `experiments/kb_main.yaml`). See
[`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) for the experimental setup,
[`docs/APPENDIX_V1_V2.md`](docs/APPENDIX_V1_V2.md) for how it relates to the v1 study, [`docs/paper/`](docs/paper/README.md) for the paper draft (introduction to discussion, LaTeX math), and
[`docs/DESIGN.md`](docs/DESIGN.md) for how v2 addresses v1's problems.

## Development

```bash
uv pip install -e ".[dev]"
pytest -q          # 77 tests, fully offline (~30 s), including a 100k-word novel run
ruff check .
saga experiment experiments/offline_demo.yaml       # whole experiment loop with the fake model
```
