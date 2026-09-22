# Generation Pipeline Design

## 1. Purpose and Scope

`EXPERIMENTAL_SETUP.md` defines seven generation conditions (C1–C7) across
four generation tasks (A–D), run over two or more generator families, on a
29-item corpus plus a 10-item scratch sub-corpus — 952 generated stories at
confirmatory scale, each of which must carry the provenance
`EXPERIMENTAL_SETUP.md` §11 requires (model identifier and revision, decoding
parameters, seeds, prompt-template hashes, full generation traces including
abandoned runs).

This document specifies the **generation pipeline**: the general-purpose
harness that dispatches a declared set of generation jobs, runs each one
through a condition-specific backend, and records its output with that
provenance attached. It does not specify:

- **The judging/instrument pipeline** (A1–A6, Q1, M1/M2, S1/S2 in
  `EXPERIMENTAL_SETUP.md` §5) — a separate subsystem that consumes this
  pipeline's output, designed separately.
- **Condition backends beyond C1** — C2–C7 are registered as stubs (see §5)
  so the runner/registry/storage design is proven end-to-end against one real
  backend before the remaining six are built as their own follow-up tasks.
- **Authoring premises, gold specifications, or scratch specifications** —
  the corpus (`experiments/data/stories/corpus.parquet`) currently holds only
  source texts. This pipeline defines how such inputs are *referenced*
  (§4) but not how they are produced.

## 2. Job Model

A **`GenerationJob`** is the atomic unit of work:

```
(plan_name, task, condition, item_id, generator_family, language, replicate, is_pilot)
```

- `task` ∈ {A, B, C, D}, `condition` ∈ {C1..C7}, per `EXPERIMENTAL_SETUP.md` §3–4.
- `item_id` refers to a `corpus.parquet` row (Tasks A, C), a scratch-corpus id
  (Task D), or a synthetic id identifying a gold-specification input (Task B).
- `generator_family` names a configured model family (e.g. `frontier`,
  `open_weight`), resolved to a concrete model identifier via pipeline
  settings, never hardcoded per job.
- `replicate` defaults to `0`; present for forward compatibility with
  repeated generation, not currently used by the confirmatory design.
- `is_pilot` distinguishes pilot runs (excluded from analysis per
  `EXPERIMENTAL_SETUP.md` §7) from confirmatory ones. Pilot and confirmatory
  jobs for the same identity tuple are distinct rows (pilot data is never
  silently reused as confirmatory data).

`job_id` is a stable content hash of this identity tuple. Re-expanding a plan
or re-running the pipeline is idempotent: a job whose identity already exists
in the registry is never duplicated, only re-checked against its recorded
status.

## 3. Plans and Job Expansion

A YAML **plan** declares what to generate, not how:

```yaml
name: pilot
is_pilot: true
corpus_filter: {sample_per_language: 3}
tasks:
  A: {conditions: [C1, C2, C4, C5, C6], generators: [frontier, open_weight]}
  B: {conditions: [C1, C2, C3], generators: [frontier, open_weight]}
  C: {conditions: [C1], generators: [frontier, open_weight]}
  D: {conditions: [C1], generators: [frontier, open_weight]}
```

Expansion loads `corpus.parquet`, applies `corpus_filter`, and produces the
cross-product of (filtered items) × (declared conditions) × (declared
generators) × (languages present in the filtered corpus) — restricted by a
**hard-coded task/condition eligibility table** mirroring
`EXPERIMENTAL_SETUP.md` §4 (e.g. C3 is never eligible under Task A; C6 is
never eligible under Task B). A plan that names an ineligible combination is
rejected at expansion time with an explicit error, not silently dropped.

Expansion is additive and idempotent: running `expand` twice, or after
editing a plan to add a condition, inserts only the new jobs. Shrinking or
growing a run for `EXPERIMENTAL_SETUP.md` §12's reduction path is an edit to
the plan file, not a hand-edited job list.

## 4. Input Resolution

Each task consumes a different kind of input:

| Task | Input                                    |
|------|-------------------------------------------|
| A    | a premise for the item                    |
| B    | the item's gold specification             |
| C    | the item's source text                    |
| D    | a scratch specification (no source text)  |

An `InputResolver` looks up a job's input by a fixed filesystem convention:

```
experiments/data/premises/<item_id>.md
experiments/data/specs/gold/<item_id>.md
experiments/data/specs/scratch/<item_id>.md
experiments/data/stories/{english,dutch}/<source file, from corpus.parquet>
```

If the expected file is absent, the resolver raises a clear "input not
found" error identifying the missing path. A job whose input doesn't exist
yet simply cannot run — this is expected until premises/specs are authored
as separate follow-up work (§1) — but the pipeline never blocks on that
authoring, and a `status` report distinguishes "blocked on missing input"
from other failure modes.

## 5. Backends

```python
class GenerationBackend(Protocol):
    def run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult: ...
```

`GenerationResult` bundles the produced artifacts, the full raw message
trace, and the resolved reproducibility config (model identifier + revision,
decoding parameters, seed, prompt-template content hash).

`BACKEND_REGISTRY: dict[Condition, GenerationBackend]` maps C1–C7. Backends
for C2–C7 are registered as stubs that raise
`NotImplementedError("<condition> not yet implemented")`; a plan naming an
unbuilt condition fails immediately and loudly at run time, not silently.

**C1 (Full pipeline)** is the only implemented backend, since it requires no
new `psalm_saga` capability. It follows the same shape as
`run_batch()` in `psalm_saga/batch_cli.py`:

1. Generate a fresh `session_id`, open a `SqliteSaver` checkpointer scoped to
   the job's own output directory (one session per job, not one session per
   story-within-a-batch, so every job is independently resumable and
   inspectable).
2. `build_agent(settings, session_id=..., checkpointer=..., ...)`.
3. Invoke with a task-appropriate instruction: Task A gets the resolved
   premise, Task B the resolved gold spec, Task C the resolved source text
   plus the variant instruction (C1 is the only backend Task C or D ever
   route to).
4. After the run, copy the session's relevant `docs/` output into
   `experiments/runs/<job_id>/`, and serialize the LangGraph message stream
   into `trace.jsonl`.

## 6. Registry

A single SQLite database, `experiments/runs/runs.db`:

```sql
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,       -- content hash of identity fields
    plan_name TEXT,
    task TEXT, condition TEXT, item_id TEXT,
    generator_family TEXT, language TEXT,
    replicate INTEGER, is_pilot INTEGER,
    status TEXT,                   -- pending | running | done | failed | abandoned
    output_dir TEXT,
    error TEXT,
    started_at TEXT, finished_at TEXT,
    config_json TEXT               -- model id/revision, decoding params, seed, prompt hash
);
```

The registry is the single source of truth for job status. It stays lean —
heavy reproducibility payloads (traces, generated text) live on disk per job,
not in SQLite — so status queries stay fast even at confirmatory scale.

Claiming a job for execution is a single atomic
`UPDATE jobs SET status='running' WHERE job_id=? AND status='pending'`
transaction, so two concurrent workers can never claim the same job.

## 7. Storage Layout

```
experiments/
  plans/
    pilot.yaml
    confirmatory.yaml
  data/
    premises/<item_id>.md
    specs/{gold,scratch}/<item_id>.md
    stories/{english,dutch}/*.txt      # existing corpus source texts
    stories/corpus.parquet             # existing
  runs/
    runs.db
    <job_id>/
      metadata.json    # mirror of this job's registry row, human-readable
      trace.jsonl       # full raw message trace, every model call in/out
      spec.md, plan.md, chapters/, story.md, review.md   # backend-specific
```

Every job's output directory is self-contained: a later judging-pipeline
script can be pointed at one `<job_id>/` folder and read everything it needs
(the story, its provenance, its full trace) without querying SQLite.

## 8. Runner

A bounded worker pool (`ThreadPoolExecutor`, since `agent.invoke()` blocks):
each worker claims one `pending` job, dispatches it to
`BACKEND_REGISTRY[job.condition]`, and writes the result. Every per-job
exception is caught at the worker boundary and recorded as `status=failed`
with the error message attached — one failing job never stops the pool.

`--workers N` bounds concurrency only; it does not add a cross-worker rate
limiter. Each job's `build_agent()` call already wires in `psalm_saga`'s
existing per-agent rate-limiter/retry middleware (`psalm_saga/settings.py`),
so `--workers` is tuned down if provider throttling appears in practice. A
shared global limiter is deferred until the pilot run shows it's actually
needed (YAGNI).

Failed jobs do not auto-retry. This is a deliberate choice: a systematically
broken config (bad credentials, a malformed prompt) should surface as a
block of `failed` rows to investigate, not loop silently consuming budget.

## 9. CLI

All under `python -m experiments.pipeline.cli`:

| Command | Effect |
|---|---|
| `expand --plan plans/pilot.yaml` | Load a plan, insert new jobs into the registry (idempotent, additive). |
| `run --plan plans/pilot.yaml --workers 4` | Expand if needed, then run all `pending` jobs. |
| `status --plan pilot` | Counts by task × condition × status, including "blocked on missing input". |
| `retry --failed --plan pilot` | Explicitly requeue `failed` jobs as `pending`. |

## 10. Package Location

```
experiments/
  pipeline/
    __init__.py
    cli.py        # command dispatch
    plan.py       # YAML plan loading + job expansion + eligibility table
    registry.py   # SQLite job table (schema in §6)
    runner.py     # worker pool, claim/execute/record loop
    resolver.py   # InputResolver (§4)
    backends/
      __init__.py     # BACKEND_REGISTRY
      full_pipeline.py  # C1 — implemented
      no_review.py      # C2 — stub
      flat_with_spec.py # C3 — stub
      no_spec.py        # C4 — stub
      flat.py           # C5 — stub
      agents_room.py    # C6 — stub
      human.py          # C7 — stub (registers source text, no generation call)
```

A plain package under `experiments/`, not a separately installed/versioned
package — study-specific orchestration code stays visibly separate from the
reusable `psalm_saga` library, alongside the existing
`experiments/data/` and `experiments/build_corpus_dataset.py`.

## 11. Testing

- Unit tests for plan expansion (eligibility table enforcement, idempotent
  re-expansion, corpus filtering).
- Unit tests for the registry (atomic claim under concurrent access, status
  transitions).
- An integration test for the C1 backend that stubs `build_agent()`'s model
  calls (no live API calls in CI) and asserts the expected artifacts and
  `trace.jsonl` land in the job's output directory.
- A manual smoke test: a tiny plan (1 item, 1 condition, 1 generator) run
  end-to-end against a real model, to validate the full path before trusting
  it at pilot scale.

## 12. Out of Scope / Follow-on Work

- Judging/instrument pipeline (separate design).
- C2–C7 backend implementations (separate follow-up tasks each).
- Authoring premises, gold specifications, and scratch specifications
  (separate follow-up task; this pipeline only defines how they're
  referenced once they exist).
- Cross-worker global rate limiting (deferred until the pilot shows it's
  needed).
