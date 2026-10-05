# Running the experiments

This is the operator's guide to the generation experiments: what they are,
what you need before you start, how to run them, and how to read what comes
out. The study design (research questions, hypotheses, power analysis) lives
in [`EXPERIMENTAL_SETUP.md`](EXPERIMENTAL_SETUP.md). The harness design lives
in [`superpowers/specs/2026-09-22-generation-pipeline-design.md`](superpowers/specs/2026-09-22-generation-pipeline-design.md).
This document is the practical layer between them.

Commands assume you run them from the repository root.

## 1. Status at a glance

The experiments are a study of whether a story generated from an explicit
dimension specification actually instantiates the dimensions it names, and
what the specification stage contributes. The full study needs generation,
then judging, then analysis. Only the first stage exists in code.

| Stage | Status | Where |
|---|---|---|
| Source corpus (29 public-domain items, EN + NL) | Built, **not in git** (see §3.1) | `experiments/data/stories/` |
| Plan files and job expansion | Built | `experiments/plans/`, `experiments/pipeline/plan.py` |
| Job registry (SQLite) and worker pool | Built | `experiments/pipeline/registry.py`, `runner.py` |
| Generation, condition **C1** (full pipeline) | Built | `experiments/pipeline/backends/full_pipeline.py` |
| Generation, conditions **C2–C7** | Stubs; raise `NotImplementedError` | `experiments/pipeline/backends/*.py` |
| Premises, gold specs, scratch specs | **Not authored yet** | `experiments/data/{premises,specs}/` |
| Judging instruments (A1–A6, Q1) | Not built | — |
| Mechanical checks (M1 lock, M2 overlap) | Not built | — |
| Specification instruments (S1, S2) | Not built | — |
| Statistical analysis | Not built | — |

Practically: today you can generate stories with C1 and inspect them. You
cannot yet produce study results. The committed pilot plan also cannot run
end to end until premises exist (§3.3).

## 2. What the experiments are, and why

### 2.1 The question

psalm-saga writes a dimension specification (writing style, narrative voice,
character, plot structure, scene sequence, world-building, and their
sub-dimensions) before drafting prose. The study asks whether that
specification does anything: whether the generated story actually reflects
the values the specification names, and whether the staged pipeline beats
simpler alternatives. [`EXPERIMENTAL_SETUP.md` §1](EXPERIMENTAL_SETUP.md#1-research-questions)
states five research questions:

| RQ | Question | Role |
|---|---|---|
| RQ1 | Does a story generated from a specification instantiate the values that specification names? | Primary |
| RQ2 | Does the specification stage do work the rest of the pipeline does not? | Primary |
| RQ3 | When the system writes a specification from a human story, does it recover what a human annotator recorded? | Diagnostic |
| RQ4 | Is specification-driven output non-inferior in quality to unstructured baselines? | Guardrail |
| RQ5 | Does adherence depend on who wrote the specification? | Diagnostic |

### 2.2 The conditions

Each condition is a different way of producing a story. Comparing them is
how the RQ2 contrasts are drawn.

| ID | Name | Input | Pipeline | Status |
|---|---|---|---|---|
| C1 | Full | specification | spec → plan → draft → review → repair | **Implemented** |
| C2 | No Review | specification | spec → plan → draft | Stub |
| C3 | Flat+Spec | specification | single call, spec in prompt | Stub |
| C4 | No Spec | premise | premise → plan → draft → generic review | Stub |
| C5 | Flat | premise | single call from premise | Stub |
| C6 | Agents' Room | premise | multi-agent baseline (Huot et al., 2025) | Stub |
| C7 | Human | none | the source item itself (no generation) | Stub |

Why these exist:

- **C3** is the sharpest test of the pipeline. It gets the same specification
  as C1 but no plan, verification, or repair. If C1 does not beat C3, the
  pipeline adds nothing over pasting the spec into a prompt.
- **C4** removes the specification and keeps the plan-and-draft structure. It
  isolates the value of the taxonomy.
- **C6** guards against C4 being a strawman by using an independently
  published architecture.
- **C7** is the human reference point. It anchors the quality scale.

### 2.3 The tasks

A task decides what input a job gets. The same condition runs under different
tasks to separate different questions.

| Task | Input | Conditions | What it tests |
|---|---|---|---|
| A | premise | C1, C2, C4, C5, C6, C7 | Whole-system comparison from a premise alone |
| B | gold specification | C1, C2, C3 | Spec-following, separated from spec-writing |
| C | source story | C1 | Extract a spec from a human story, then make six single-dimension variants |
| D | scratch specification (authored) | C1 | Variants without the extraction step (isolates extraction error) |

Task B supplies the gold specification directly so that a system that writes
vague specs and follows them well is not confused with one that writes sharp
specs and ignores them.

Task C and D produce six variants per item, one per dimension. Each variant
regenerates one dimension and locks the other five. Note that the harness does
not verify the locks yet; that check is M1 (`EXPERIMENTAL_SETUP.md` §5.1), which is unbuilt.

### 2.4 The corpus

29 items, 15 English and 14 Dutch, each a complete scene or arc. Lengths run
from about 300 to about 8,500 words, so check `word_count` in `corpus.csv`
rather than assuming a uniform length. They are stratified across five genre buckets
(Gothic/Supernatural, Detective/Mystery, Domestic/Social Realism,
Adventure/Sea or Travel, Satire/Moral Fable), three per language per bucket,
except Dutch Detective/Mystery, which has two. The full item list and the
reason each item was picked are in [`CORPUS.md`](CORPUS.md).

A 10-item scratch sub-corpus (5 per language) has no source text. Its
specifications are authored directly, which removes extraction error and the
memorisation confound.

## 3. Before you start

### 3.1 Data

The corpus is **not in this repository**. `experiments/data/stories/` is in
`.gitignore` (line 323), so neither `corpus.csv`, `corpus.parquet`, nor the
`.txt` source files are tracked. A fresh clone has none of them. Obtain them
from the experiments data location (CORPUS.md names it as the
`psalm-saga-experiments` repo) and place them under `experiments/data/stories/`
with this layout:

```
experiments/data/stories/
  corpus.csv                  # one row per item: id, language, genre_bucket, path, word_count, ...
  english/<id>.txt
  dutch/<id>.txt
  pilot_corpus.csv            # 6-item subset used by the pilot
```

Then build the parquet files the harness reads. The build script's default
output is the pilot corpus, so pass the flags explicitly for the full corpus:

```bash
uv run python experiments/build_corpus_dataset.py                                   # -> pilot_corpus.parquet
uv run python experiments/build_corpus_dataset.py --csv-name corpus.csv --filename corpus.parquet   # -> corpus.parquet
```

The build step warns, but does not fail, if word or character counts in the
CSV disagree with the files.

### 3.2 Environment

- **Python 3.14+** and [`uv`](https://docs.astral.sh/uv/). The `experiments`
  dependency group (pandas, pyarrow, pyyaml) is in the default groups, so a
  plain `uv sync` installs it.
- **Provider API keys** for the models your plan will call. Keys go in a
  `.env` file at the repository root (`load_dotenv()` runs at CLI start) or in
  the environment. Each provider's SDK reads its own variable, for example
  `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

```bash
uv sync --extra anthropic --extra openai
```

Generator families are symbolic names in a plan, resolved to concrete models
in `experiments/pipeline/generators.py`:

| Family | Default model | Override |
|---|---|---|
| `frontier` | `anthropic:claude-sonnet-4-6` | `PSALM_SAGA_EXPERIMENTS_GENERATOR_FRONTIER` |
| `open_weight` | `openai:gpt-oss-120b` | `PSALM_SAGA_EXPERIMENTS_GENERATOR_OPEN_WEIGHT` |

Set the override in `.env` to repoint a family without editing code. Any model
string `init_chat_model` accepts works. Record the exact model you ran, because
it is written into every job's `metadata.json` (§6.2).

### 3.3 Inputs per task

A job cannot run until its input file exists. The resolver checks for the file
before any model call, so a missing input fails in milliseconds and costs
nothing.

| Task | Expected file | Status |
|---|---|---|
| A | `experiments/data/premises/<item_id>.md` | **Not authored** |
| B | `experiments/data/specs/gold/<item_id>.md` | **Not authored** |
| C | `experiments/data/stories/<language>/<id>.txt` (from the corpus) | Present once §3.1 is done |
| D | `experiments/data/specs/scratch/<item_id>.md` | **Not authored** |

Authoring premises and specifications is separate follow-up work (design spec
§1). Until it is done, **only Task C can run**. The committed pilot plan uses
Task A, so it fails (§8).

**Premises are not the same as the corpus.** The parquet and the `.txt` files
hold each item's *full story text*. The pipeline reads that text only for
Task C, and only from the `.txt` file: the resolver builds the path from
`stories/<language>/<item_id>.txt` and never opens the parquet. The parquet's
role is job expansion (item ids and languages).

A premise is a different artifact. It is a short description of the
*situation* (who, where, what happens, how it ends) that deliberately does
not prescribe the telling: no prose, no style, no narration. Task A gives it
to the model, which must write its own story from it. Premises are written
for each corpus item (`EXPERIMENTAL_SETUP.md` §4 Task A), and they must not be
the story itself. If a premise contains the source's sentences, Task A stops
testing generation and starts testing recall. The resolver accepts any
Markdown file, so the format is free, but keep it to the situation.

For the pilot, the two items Task A would use are
`adventure_two_years_before_the_mast_ch6` and `domestic_de_ooievaar_komt`, so
you need `experiments/data/premises/adventure_two_years_before_the_mast_ch6.md`
and `experiments/data/premises/domestic_de_ooievaar_komt.md`. For the full
study, one per item (29).

### 3.4 Budget

Every C1 job is a full agent session: many model calls for spec, plan,
drafting, review, and repair. Cost scales with jobs × model price × session
length. The confirmatory design is 952 generated stories (EXPERIMENTAL_SETUP
§4). Estimate cost before a large run with `docs/experimental_cost_estimation.xlsx`.
Run a pilot first and measure real cost per job.

## 4. Plans

A plan is a YAML file declaring *what* to generate. It does not say how. The
harness expands it into one job per (item × task × condition × generator).

The committed pilot, `experiments/plans/pilot.yaml`:

```yaml
name: pilot
is_pilot: true
corpus_filter:
  sample_per_language: 1     # first item per language, ordered by id -> 2 items
tasks:
  A:
    conditions: [C1]
    generators: [frontier]
```

Fields:

- `name` identifies the plan. Status and run commands use it to select jobs.
- `is_pilot` marks every job from this plan as pilot. Pilot jobs are excluded
  from analysis (EXPERIMENTAL_SETUP §7), and a pilot job and a confirmatory job
  with the same item are stored as separate rows.
- `corpus_filter` accepts `languages: [english, dutch]` and/or
  `sample_per_language: N`. The sample is deterministic: first N by item id
  within each language.
- `tasks` maps each task to its `conditions` and `generators`.

The harness rejects ineligible pairings when it loads the plan. For example,
`C3` under Task A raises `PlanError`, and so does `C6` under Task B. Eligibility
follows EXPERIMENTAL_SETUP §4.

### 4.1 A plan that can run today

Task C is the only task whose input is already present. This plan produces two
jobs (one per language), each extracting a spec from a source story and
generating variants:

```yaml
name: pilot-taskc
is_pilot: true
corpus_filter:
  sample_per_language: 1
tasks:
  C:
    conditions: [C1]
    generators: [frontier]
```

Save it as `experiments/plans/pilot-taskc.yaml` and use it in §5 in place of
`pilot.yaml`. This is a suggestion, not a committed plan. Check that it is the
run you want before spending budget on it.

## 5. Running

The steps below use `pilot.yaml` for the command shape. Once §3.3 is satisfied
for your plan, the commands are the same.

### 5.1 Expand

Writes jobs into the registry as `pending`. Idempotent: running it again adds
only jobs that are new.

```bash
uv run python -m experiments.pipeline.cli expand \
  --plan experiments/plans/pilot.yaml \
  --corpus experiments/data/stories/pilot_corpus.parquet
```

Expected output for the pilot: `Plan 'pilot': 2 jobs described, 2 newly inserted.`

### 5.2 Run

Expands if needed, then runs every `pending` job. Prints counts by status at
the end.

```bash
uv run python -m experiments.pipeline.cli run \
  --plan experiments/plans/pilot.yaml \
  --corpus experiments/data/stories/pilot_corpus.parquet \
  --workers 1
```

- `--workers` bounds concurrency. The default is 1. Raise it only after the
  pilot shows your provider's rate limits are not a problem. Retry middleware
  is per agent; there is no global limiter yet.
- Failures do not stop the run. Each failed job is recorded and the rest carry
  on.
- Re-running `run` is safe: finished (`done`) jobs are never repeated.

For the full corpus, pass `--corpus experiments/data/stories/corpus.parquet`.
The CLI defaults to `pilot_corpus.parquet`, so omitting the flag silently runs
against the pilot subset.

### 5.3 Status

```bash
uv run python -m experiments.pipeline.cli status --plan-name pilot
```

Prints the count of jobs in each status for that plan (§6.1).

### 5.4 Retry

Requeues every `failed` job for the plan as `pending`:

```bash
uv run python -m experiments.pipeline.cli retry --failed --plan-name pilot
```

Failed jobs never retry on their own. This is deliberate: a broken setting (a
bad key, a malformed prompt) should show up as a block of failures to
investigate, not burn budget in a loop. Fix the cause first, then retry.

### 5.5 Other flags

All subcommands accept:

- `--runs-dir` (default `experiments/runs`). Holds `runs.db` and the per-job
  output folders. Gitignored.
- `--data-dir` (default `experiments/data`). Root for premises, specs, and
  stories.

Use a throwaway `--runs-dir` for a dry run, so a test does not pollute the
real registry.

## 6. Where the output goes

### 6.1 The registry

`experiments/runs/runs.db` is the single source of truth for job status. One
row per job:

| Status | Meaning |
|---|---|
| `pending` | Expanded, not yet run. |
| `running` | Claimed by a worker. If this persists after a run ends, the process died mid-job. Inspect before retrying. |
| `done` | Finished. `output_dir` and `config_json` are set. |
| `failed` | Raised an error. `error` holds the message. |
| `abandoned` | Defined in the schema but no code sets it yet. |

The design spec calls for `status` to separate "blocked on missing input" from
other failures. The current `status` command does not. Inputs that are missing
show up as `failed`, with an `error` that starts with `No <kind> input`. Use
`error` to tell them apart (§8).

You can query the registry directly:

```bash
uv run python -c "import sqlite3; c=sqlite3.connect('experiments/runs/runs.db'); print(c.execute('select item_id, task, condition, status, error from jobs').fetchall())"
```

### 6.2 Each job's folder

Every `done` job writes `experiments/runs/<job_id>/`:

```
experiments/runs/<job_id>/
  metadata.json     # identity fields plus `config`: what was actually run
  trace.jsonl       # one line per message in the agent's run, in order
  drafts/           # per-story working area: spec, plan, chapters, review report
  stories/          # promoted, finished stories: <story_name>.md
  ...               # any other files from the session's docs/ tree
```

`job_id` is a 16-character hash of the job's identity fields, so the same
job always lands in the same folder.

`metadata.json` `config` records the reproducibility snapshot:

- `orchestration_model_name`, `subagent_model_name`, `model_kwargs`,
  `subagent_model_kwargs`: the models and provider options used.
- `task`, `condition`: what ran.
- `promoted_stories`: names of stories the run finished. Empty means no story.
- `prompt_template_sha256`: a hash of the instruction template for this task.
  Two jobs with the same hash were sent the same instruction text.
- `psalm_saga_session_id`: the session directory with the full checkpoint
  database, if you need to replay the run.

## 7. Reading the results

### 7.1 What you can read today

There is no judge yet, so there are no scores. For each `done` job you can
read:

1. **Did it finish?** `promoted_stories` in `metadata.json` is non-empty, or
   the job would have failed. A story exists under `stories/`.
2. **What did the agent do?** `trace.jsonl` is the full message sequence. Read
   the last few entries to see how the run ended.
3. **What did the spec and plan commit to?** The draft spec and plan under
   `drafts/<story_name>/` are the things the study measures adherence to. Put
   them next to the story to check the story against them by hand.
4. **Did the same instruction go out twice?** Compare `prompt_template_sha256`
   across jobs. It should match within a task.

Reading a handful of outputs by hand is the sanity check to do before anything
else. Confirm the story is what the spec describes, that the trace shows the
pipeline stages, and that the job is not a truncated draft.

### 7.2 What the study will compute

These are not built, but the design fixes how their results should be read,
so it is worth knowing before they arrive. Full detail is in
[`EXPERIMENTAL_SETUP.md` §5](EXPERIMENTAL_SETUP.md#5-instruments) and
[§8–9](EXPERIMENTAL_SETUP.md#8-analysis).

**The chance level matters more than the raw accuracy.** Each judging task has
a different chance rate, and a result only means something relative to it:

| Instrument | Question | Chance | What a result means |
|---|---|---|---|
| A1 dimension ID | Which of six dimensions was regenerated? | 1/6 ≈ 0.167 | Accuracy above 0.167 means the variant carries its regenerated dimension detectably. |
| A2 drift | Did any locked dimension also change? | — | Reported as d′ (hit rate on the changed dimension vs false-alarm rate on locked ones). |
| A3 spec→story matching | Which of two stories came from this spec? | 1/2 | Above 0.5 means the story reflects its spec. |
| A4 story→spec attribution | Which of three specs did this story come from? | 1/3 | Above 0.33 means the story reflects its spec. |
| A5 sub-dimension recovery | Which of four values is true for this sub-dimension? | 1/4 | Exploratory. Reported descriptively. |
| A6 premise attribution | Which of three premises did this story come from? | 1/3 | **Calibration, not a result.** Every condition should approach ceiling (the study reports about 0.94). A condition far below it signals a generation failure, not poor adherence. |

Reading the numbers:

- **The confusion matrix on A1** is often more informative than the accuracy.
  Systematic confusion between two dimensions, such as Writing Style and
  Narrative Voice, says something about the taxonomy, not the generator.
- **"Cannot tell" is an allowed answer.** The primary analysis excludes
  abstentions and reports the abstention rate beside it. A secondary analysis
  counts them as wrong.
- **H1d is conditional.** A2 is only scored on items where A1 was right. If
  that subset is under 60 items, the design says to report an unconditional
  drift rate instead and call H1d inconclusive.
- **Pairwise comparisons (Q1, the C1–C3 and C1–C4 contrasts) are not powered
  below 15 percentage points.** A null inside that band is not evidence of no
  effect. The study says so in advance.
- **Multiple tests are corrected** with Benjamini–Hochberg at q = 0.05, within
  three families (dimension tests, condition contrasts, language contrasts).
  Each p-value is reported with a marginal probability, an interval, and an
  odds ratio.
- **Model judges are never from the generator families.** Judge families are
  disjoint from generator families, which designs out self-preference. A
  Rogan–Gladen correction, estimated from a human subset, adjusts raw judge
  accuracy for judge error.

### 7.3 Pilot data is never analysed

Pilot runs are tagged `is_pilot` and are excluded from the confirmatory
analysis. The pilot exists to decide things: whether open-weight models
produce coherent stories and 36-field specs, which judges clear the gates, the
observed abstention rate (which sizes the H1d check), and median human time per
item. Do not mix pilot and confirmatory output in one analysis.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Corpus file not found: .../pilot_corpus.parquet` | Build step not run (§3.1). | Run `build_corpus_dataset.py`. |
| `No premise input for job ... expected experiments\data\premises\<id>.md` | Task A needs premises, which are not authored yet. | Author the premise file, or use a Task C plan (§4.1). |
| `No gold_spec / scratch_spec input ...` | Task B or D needs specs, which are not authored yet. | Author the spec file. |
| `No story was completed for job ...: no draft ... carries a DONE.md marker` | The agent ran but did not finish a story. It may have hit a model-call or tool-call limit, or stopped early. | Read `trace.jsonl`'s last entries to see where it stopped. Raise the limits in `psalm_saga/settings.py` if they are the cause, then `retry --failed`. |
| `C2 backend is not yet implemented` (or C3–C7) | A plan names an unbuilt condition. | Use C1 only. |
| `Plan ...: Task A does not run condition C3` (`PlanError`) | Ineligible task/condition pairing. | See the eligibility table in §4. |
| `No model configured for generator family 'x'` | Unknown family. | Use `frontier` or `open_weight`, or add an override env var. |
| Job stuck as `running` after the process stopped | Process died mid-job. | Check nothing is still running, then `UPDATE jobs SET status='pending' WHERE status='running'` (direct SQLite) and re-run. |
| `status` shows `failed` with no hint why | Inspect the error text. | `select item_id, error from jobs where status='failed'` (see §6.1). |

## 9. Reproducibility

The confirmatory design requires everything needed to re-run a result to be
published before the run (EXPERIMENTAL_SETUP §11). The current harness records
part of that:

**Recorded now:** model identifiers, provider options, the prompt-template
hash, the session id, every message in the trace, the plan and job identity,
and the corpus item used.

**Not recorded yet:** exact model revisions, decoding parameters (temperature
and the like), seeds, and the repair bound. The study requires these. Add them
to `config` before any run you intend to report.

Also keep the full `runs/` tree, including failed and abandoned runs.
Abandonment rate is a reported quantity (`EXPERIMENTAL_SETUP.md` §10), so dropping failures would bias
the analysis.

## 10. Development

The experiment harness has its own tests:

```bash
uv run pytest tests/experiments
```

These cover plan expansion and eligibility, the registry (including atomic
claims), input resolution, generator mapping, the runner, and the C1 backend,
with the model calls stubbed. They make no live API calls and cost nothing.

When you add a backend, implement `GenerationBackend.run` in its own module,
register it in `experiments/pipeline/backends/__init__.py`, and add a test
alongside `tests/experiments/test_full_pipeline.py`. Keep backends pure: they
return a `GenerationResult`, and the runner writes it to disk.

## 11. File map

| Path | Purpose |
|---|---|
| `EXPERIMENTAL_SETUP.md` | Study design: RQs, conditions, instruments, analysis, power. |
| `EXPERIMENT_DRAFT.md` | Shorter draft of the same design, with less detail. `EXPERIMENTAL_SETUP.md` is the fuller version and the one the harness spec cites. |
| `CORPUS.md` | Corpus appendix: each item, its bucket, and why it was picked. |
| `superpowers/specs/2026-09-22-generation-pipeline-design.md` | Harness design: job model, registry schema, backends, CLI. |
| `experiments/plans/*.yaml` | Plans. |
| `experiments/pipeline/` | Harness code. `cli.py` is the entry point. |
| `experiments/build_corpus_dataset.py` | Builds the corpus parquet from CSV + text. |
| `experiments/data/` | Corpus, premises, specs (gitignored, §3). |
| `experiments/runs/` | Registry and job output (gitignored). |
| `tests/experiments/` | Harness tests. |
