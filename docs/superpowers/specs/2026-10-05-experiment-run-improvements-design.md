# Experiment Run Improvements Design

Date: 2026-10-05
Scope: `experiments/pipeline/` (generation harness). No changes to `psalm_saga` skills.
Status: approved in chat; pending user review of this file before the implementation plan.

## Context

The pilot Task A run (see `docs/EXPERIMENTS.md`) produced one finished story and one
failed job. The failed job's session had been abandoned after the per-chapter fix-loop
cap (3 attempts), but the harness reported it as `failed` with a misleading message.
Four gaps came out of that run.

## 1. Length matches the source

- The backend reads `word_count` from the job's corpus row and sets a target band of
  ±10%. A 300-word source gives 270–330.
- The band goes through `psalm_saga.story_length.parse_length` (as `MIN-MAX`) and
  `format_length_directive`, and the directive is included in the instruction for every task.
- Task D has no source text, so its plan must set a length explicitly, using a `length:`
  key (`{min: N, max: M}` or a word count).
- Each job's `metadata.json` records the target range and the realised word count of the
  promoted story.

## 2. Progress reporting

- `FullPipelineBackend` switches from `agent.invoke` to `agent.stream`. Stage changes are
  detected from tool calls: writing spec, plan, or chapter files, and dispatching
  `chapter-writer` or `dimension-reviewer`.
- The runner prints one line when a job starts and one when it finishes, with `n of N`
  and elapsed time. Stage lines (e.g. `draft ch 2/5`, `fix attempt 2`) are printed as they occur.
- Each job also writes `runs/<job_id>/progress.log` with the same lines.

## 3. Run a single item

- `run --item <corpus_id>` is repeatable. It restricts which **pending** jobs are claimed.
- `expand` still covers the whole plan, so a single-item run does not change any other row.
- Only `pending` jobs are claimed, so `done` jobs are never repeated and the result of
  running items one at a time matches a single full run (job ids depend only on identity fields).
- `failed` and `abandoned` jobs are not claimed by `run`; they need `retry`.
- An unknown id fails with the list of valid ids from the corpus.

## 4. Abandonment

- After a story attempt, the backend checks for `ABANDONED.md` and reads its reason.
- Per-chapter fix-loop cap stays at 3 (`reviewing-story-dimensions`).
- A job makes up to 3 story attempts, each in a fresh session. Each attempt's artifacts
  and trace are kept under `runs/<job_id>/attempts/<n>/`.
- `runs/<job_id>/attempts.jsonl` records:
  - `attempt_started` (attempt number, session id, timestamp)
  - `fix_loop_activated` (chapter, cycle, timestamp, failing dimensions)
  - `attempt_abandoned` (reason from `ABANDONED.md`, timestamp)
  - `attempt_done` (promoted story name, timestamp)
- Job status:
  - `done` if any attempt promotes a story.
  - `abandoned` if all 3 attempts are abandoned. The reason is stored in `error`.
  - `failed` only for real errors (exceptions, missing inputs, unimplemented conditions).
- `retry --failed` also requeues `abandoned` jobs.
- The misleading "no story was completed" message is removed; the real reason is recorded.

## Testing

- Unit: band derivation from `word_count`; `--item` filtering (including unknown ids and
  that `done` jobs are not reclaimed); attempt sequencing with a stubbed backend (abandon
  twice, then succeed; abandon three times); status transitions including `abandoned`.
- Unit: stage detection from a recorded event list.
- Manual: rerun the pilot's `domestic_de_ooievaar_komt` with `--item` after implementation.

## Out of scope

- Judging, M1/M2 checks, C2–C7 backends.
- Changing the per-chapter cap.
