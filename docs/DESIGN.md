# Design: what changed from v1 and why

v1 was a single LangGraph/deepagents agent steered by `SKILL.md` prompts: the model
decided, call by call, when to brainstorm, plan, dispatch a writer subagent, review and fix.
v2 keeps the method — spec first, then plan, then draft with a review loop, over the six PSALM
dimensions — but runs it as an explicit **workflow**: a fixed, configurable sequence of
stages, each a handful of narrowly scoped model calls with typed outputs, persisted to disk.

Agents are the right tool when the next step is not known in advance. Here it is known. An
orchestrating agent costs extra turns (planning what to do, re-reading files, tool-call
chatter), makes cost and runtime unpredictable, and makes experiments hard to control: two
runs of the "same" condition do not even execute the same steps. A workflow fixes all three.
The interactive, agent-like experience moves to the interface (`saga chat`, the web app),
where a person steers between checkpoints.

## v1 problems → v2 mechanisms

| Problem in v1 | What v2 does |
|---|---|
| **Slow, wastes tokens** | No orchestrator turns. Each call gets only what it needs: drafting sees the spec (cached prefix), the cast of *this* chapter, *this* chapter's plan and the previous chapter's planned ending — never the whole story so far. Spec dimensions, chapter plans, chapter drafts and reviews run in parallel. Repairs are paragraph-level edits, not chapter rewrites. Preserved dimensions are transformed deterministically. Responses are cached on disk. |
| **Can't handle long input (100k words)** | `extract` splits on chapter headings (multilingual, skipping tables of contents), cuts long chapters on paragraph boundaries, analyses chunks in parallel (map), merges entities deterministically and consolidates aliases in one compact call (reduce). Nothing downstream ever sees the full text. The test suite runs a 102k-word, 30-chapter novel and asserts no call exceeds 20k prompt tokens. |
| **Takes long, times out** | Streaming generation (no idle-connection timeouts), a hard per-call timeout with retry, automatic continuation when output hits `max_tokens`, parallel stages, and long chapters drafted scene by scene. |
| **Rate limits handled badly** | Per-model limiter shared by all concurrent calls: concurrency cap, RPM/TPM token buckets, and a shared cooldown — a 429's `Retry-After` pauses every caller of that model, rather than each discovering the limit separately. Jittered exponential backoff for 5xx/timeouts; fatal errors (auth, context window) fail fast. |
| **Crashes lose work** | Every chunk, spec, plan, chapter and review is a file. `resume` skips everything finished, down to individual chunks and chapters. |
| **Spec and plan not detailed enough** | One call per dimension (six focused calls rather than 36 sub-dimensions in one answer), with instructions to name mechanisms and behaviours rather than labels, and measured stylometrics as hard targets for writing style. Planning is hierarchical: an outline, then one call per chapter producing scenes with 3–7 concrete beats, word budgets and the spec commitments the chapter must visibly realise. |
| **Review overly critical** | The reviewer reports only violations of *explicit* commitments, with evidence; severities are defined; it is told that an empty list is the normal outcome; only `major`+ issues trigger a repair (`threshold`); rounds are bounded (`rounds`, default 1); a repair is kept only if it does not make things worse. Each issue names where it comes from and is fixed there: prose issues by paragraph edits, plan issues by revising that chapter's plan and redrafting the chapter, spec or bible issues by amending the spec/bible once and going back to planning (`max_backtracks`, default 1; logged in `backtracks.json`). |
| **Outdated prompts** | Rewritten as short Jinja templates in `psalm_saga/prompts/`, written for current models (explain the purpose, state constraints once, no shouting, structured output by schema). `prompts_dir` overrides any template per experiment or model family without code changes. |
| **Stiff, hard to change** | Stages are registered by `(name, impl)`; presets are YAML with inheritance; every field is overridable (`--set`, SDK dict, web form). Baselines and ablations are presets, not separate code paths. Per-stage models via roles. Taxonomy is a YAML file. |
| **Prose in the model's own register** (found in testing: half-length sentences, one-line paragraphs, invented dialogue) | Drafting prompts carry the source's measured rhythm as numbers (sentence-length quantiles, paragraph length, speech share, punctuation); a `conform` stage measures each chapter and revises rhythm and layout only, keeping a revision only if it moves closer to the targets without changing length, language or variety. Renaming is restricted to proper names, so descriptions ("the mother") are no longer replaced by names or long phrases. |
| **Verse turned into prose; every text treated as prose** (found in testing on a collection of rhymed poems) | Form is measured on the source (`text/form.py`: prose, verse or drama; for verse: words per line, lines per stanza, rhyme share and scheme, poem titles, in any Latin-script language). A collection of titled poems is split into one chapter per poem. Spec, plan and drafting prompts state the form; a draft in the wrong form is redrafted; conform steers line length, stanza size and rhyme for verse; evaluation compares form. |
| **Line breaks doubled on Windows** | A CRLF upload written in text mode became `\r\r\n` and read back with a blank line after every line, so every line counted as a paragraph. Text is now stored with `\n` only and read with line endings normalised; texts that mark paragraphs by single line breaks are recognised as such. |
| **Wrong output language / English headings** | Language is detected from the input (or set explicitly) and stated in every system prompt. Every drafted chapter is language-checked and redrafted on mismatch. Models output prose only; headings are rendered by code from a localised table ("Hoofdstuk", "Kapitel", "Chapitre", …), and stray model headings are stripped. |
| **Experiment setup too complex** | A lean design around the claim the library needs (`docs/EXPERIMENTS.md`), with automatic instruments first and judges that compare specs rather than whole books. |

## The clean-room boundary

In source mode, only `extract`, `spec` (describing the source) and `transform` read the
source text. `transform` turns the source spec and story bible into a synthetic spec and
bible: names replaced consistently (including aliases, short forms and possessives), the
setting shifted, and each dimension carried over under its policy. Planning and drafting
see only the transformed artifacts. Two things follow:

1. Leakage can only enter through the spec and bible (which are short, inspectable and
   written "in your own words"), or through the model's own memory of a famous text.
2. The `guard` stage measures exactly that: verbatim spans of ≥ `min_span` words shared with
   the source are found deterministically (an n-gram index built once per run) and only the
   affected paragraphs are rewritten; surviving original names are replaced from the rename
   table without a model call. What remains is reported, not hidden.

The `paraphrase` and `flat` baselines deliberately cross this boundary (the writer sees the
source), which is what makes them informative comparisons.

## Language variety

"Same language" is not enough for historical or dialectal sources: a modern-Dutch rewrite of
a 19th-century Dutch novel keeps the language and changes the style. v2 treats the variety as
part of the language constraint. Analysis asks the model to name the variety and propose
marker pairs (variety form, standard form); each marker is kept only if the source uses it at
least twice, uses it more often than its standard form, and it is not a name. The share of
variety forms among all marker occurrences is then a deterministic measure, computed the same
way on source and synthetic text. Drafting states the variety in every prompt, and a chapter
whose share falls well below the source's is redrafted with the modern forms it used named.
Markers are single words, never phrases, so they carry no protected expression.

## Story bible

A lightweight knowledge base rather than a full graph database: entities (with aliases,
role, chapters present, mention counts computed from the text), typed relations, and per
chapter the scenes and causally linked events. It drives scoped drafting context, the
skeleton that planning follows in source mode, the character-network fidelity metrics, and
the bible view in the web app. `psalm_saga/graph.py` turns it into a typed graph (entities, scenes, events, chapters; relations,
co-occurrence, settings, involvement, causality, sequence), which the web app explores with a
vendored Cytoscape.js (no CDN, so it works offline) and `saga graph` exports as GraphML.
Causal links come from the extraction itself (`cause_index`, within a passage) or are inferred
across passages by matching the stated cause to earlier events; inferred links are marked.
The full technical design — construction, graph schema, variants, comparison and its scores,
consumers, configuration and limitations — is in [KNOWLEDGE_GRAPH.md](KNOWLEDGE_GRAPH.md).

## Where things live

```
psalm_saga/
  config.py            PipelineConfig, presets, overrides
  pipeline.py          stage engine: resume, rerun_from, until, status
  sdk.py               Saga / Run: synthesize, write, edit, put
  llm/                 client (retries, streaming, cache, structured output), limiter, fake model
  stages/              extract, spec, transform, plan, draft, review, guard, assemble, evaluate, baselines
  text/                chunking, language, metrics (stylometrics, leakage)
  eval/                automatic evaluation, model judges
  experiments/         grid runner
  prompts/             Jinja templates
  presets/             YAML conditions
  taxonomies/          dimension taxonomy
  cli/, web/           interfaces
```
