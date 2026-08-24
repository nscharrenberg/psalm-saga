# Batch story generation (non-interactive mode)

Status: approved design, not yet implemented.

## Motivation

Every psalm-saga session today assumes a human in the loop: `story-brainstorming`
and `adapting-existing-work` elicit dimension choices by asking questions,
`writing-story-plans` waits for explicit sign-off, and
`reviewing-story-dimensions` asks the human to judge ambiguous `Partial`
findings. This is the right default for a single story someone is
deliberately authoring, but it rules out generating many stories at once —
this is item one on the README roadmap ("non-interactive mode for batch
generation").

This design adds a second, non-interactive entry point that generates N
complete stories in one session, end to end, with no questions asked and no
human checkpoints, while reusing the existing subagent architecture
(`chapter-writer`, `dimension-reviewer`) and settings/session plumbing
unchanged. The interactive path (`psalm-saga`) and its skills' hard gates
are not modified in their default behavior — batch mode is additive.

## Goals

- A `psalm-saga-batch` command that generates `--count` stories in a single
  session, under four input modes: from scratch, inspired by user-supplied
  context, seeded from user-supplied templates, or generated as variants of
  user-supplied source stories with one or more dimensions changed.
- The system never asks the user anything during a batch run — every
  creative decision a human would normally make interactively is made by
  the system itself.
- Every dimension still gets an explicit answer, still gets written to a
  spec, still gets carried through a plan, and every chapter still goes
  through the same per-chapter draft/review loop as interactive mode —
  batch mode changes *who* decides and *whether there's a pause*, not
  *whether the process happens*.
- Finished stories are promoted to a predictable, stable location per
  session; work in progress is kept separately.

## Non-goals

- Changing interactive (`psalm-saga`) session behavior, directory layout,
  or any of the existing skills' default (non-batch) instructions.
- Parallelizing story generation within a batch (out of scope for this
  design; stories are generated one at a time, sequentially, within one
  session).
- A GUI or web interface (tracked separately on the README roadmap).

## CLI surface

A new console script, `psalm-saga-batch`, alongside the existing
`psalm-saga`:

```
psalm-saga-batch --count N --mode {scratch,context,template,variant}
  [--context TEXT ...] [--context-path PATH ...]      # mode=context
  [--template-path PATH ...]                          # mode=template
  [--source-path PATH ...] [--variant-manifest FILE]  # mode=variant
  [--combine {mixed,separate}]
  [--session SESSION_ID] [--model MODEL]
```

- `--count N`: target total number of finished stories under
  `docs/stories/` for this session (see Resume handling below — re-running
  against an existing session only tops up the remainder).
- `--mode scratch`: no additional inputs. The system invents premise and
  all six dimensions freely.
- `--mode context`: `--context TEXT` (repeatable, an inline free-text
  description used as inspiration) and/or `--context-path PATH`
  (repeatable; `PATH` may be a file or a directory, in which case every
  file directly inside it is used). At least one of `--context` /
  `--context-path` is required.
- `--mode template`: `--template-path PATH` (repeatable; file or
  directory, same expansion rule as context). Template documents are seed
  material — partial dimension answers the system creatively completes,
  not complete specs used verbatim.
- `--mode variant`: `--source-path PATH` (repeatable; file or directory)
  plus an optional `--variant-manifest FILE`, a JSON file mapping each
  source to the dimension(s) that should change for it, e.g.:

  ```json
  [
    {"source": "sources/old-draft.md", "dimensions": ["character", "world-building"]},
    {"source": "sources/other.md", "dimensions": ["plot-structure"]}
  ]
  ```

  Dimension names match the existing reference-file slugs: `writing-style`,
  `narrative-voice`, `character`, `plot-structure`, `scene-sequence`,
  `world-building`. If `--variant-manifest` is omitted and a
  `--source-path` is a directory, the CLI looks for
  `<dir>/variant-manifest.json` inside it; if none is found anywhere, this
  is a hard error — variant mode never infers which dimensions to change on
  its own.
- `--combine {mixed,separate}`: how multiple inputs map onto the requested
  count.
  - `mixed` (default for `context` and `template`): the pool of inputs can
    be freely recombined — any single story may draw on one or more of
    them together.
  - `separate` (default for, and the *only* legal value for, `variant`):
    each input maps only to its own subset of the `--count` stories, never
    blended with another input in the same story. Passing `--combine
    mixed` with `--mode variant` is a validation error. Rationale: a
    "variant of a source" locks one baseline per story per
    `story-brainstorming`'s existing Source-Derived Variance Check;
    blending two sources' locked dimensions together stops being a variant
    of either one.
- `--session SESSION_ID`: resume/target a specific session, same semantics
  as `psalm-saga --session`.
- `--model MODEL`: same override as `psalm-saga --model`.

## Directory layout & session semantics

Batch sessions reuse the existing `sessions/<session_id>/` structure
(`session.py` is unchanged) but lay out `docs/` differently from
interactive sessions:

```
sessions/<session_id>/
  checkpoints.sqlite
  docs/
    drafts/
      <story_name>/
        <story_name>-spec.md
        <story_name>-plan.md
        <chapter files>
        <story_name>-review.md
    stories/
      <story_name>/
        <story_name>-spec.md
        <story_name>-plan.md
        <chapter files>
        <story_name>-review.md
```

`docs/drafts/<story_name>/` is a story's working directory while its
pipeline runs. `docs/stories/<story_name>/` is populated by copying the
draft directory once that story's whole-story review is fully clean — see
Fix-loop safety bound below for what happens if it never gets there.
Interactive sessions keep today's `docs/psalm-saga/<slug>-spec.md`
convention untouched; this layout only applies to sessions started via
`psalm-saga-batch`. Each story picks its own kebab-case `story_name` from
its own premise (same convention as today's `<slug>`); the CLI passes the
current set of names under both `docs/drafts/` and `docs/stories/` into
each per-story instruction so the model never reuses a claimed name.

## Per-story pipeline

The CLI builds one agent for the batch session (same `build_agent`,
subagent registrations, backend, and middleware as `psalm-saga`), with one
addition to the system prompt: a new `batch-story-generation` skill is
force-injected in place of `using-psalm-saga`'s human-dialogue framing for
this session. The CLI then sends one instruction message per story on the
same thread — the same "one turn at a time" pattern the interactive REPL
already uses, just generated by the CLI instead of typed by a human, e.g.:

> Generate story 3 of 10. Mode: template. Inputs: [resolved file list].
> Combine: mixed. Existing names in this session: [...]. Use the
> batch-story-generation skill.

For each story, the orchestrator runs, entirely inline (no new subagent
type — `chapter-writer` and `dimension-reviewer` are unchanged and
dispatched exactly as in interactive mode):

1. **Autonomous brainstorming** — a new "Autonomous Mode" section in
   `story-brainstorming` (only active when explicitly told this is a batch
   run): reads the same six dimension reference files, but decides every
   dimension itself instead of asking, seeded per mode:
   - *scratch*: invents premise and all six dimensions freely. To keep a
     multi-story batch actually diverse, the skill maintains a running log
     of prior stories' genre/voice/premise in this session
     (`docs/drafts/_batch-log.md`), covering both already-promoted
     `docs/stories/` entries and the current run's drafts (so a resumed
     batch still checks against everything generated in earlier runs of
     the same session), and checks each new story against it before
     locking anything, re-rolling on a near-duplicate.
   - *context*: reads the given text/files as inspiration only; no
     dimension is pre-set.
   - *template*: reads the given file(s) as partial dimension answers and
     creatively fills in whatever's left.
   - *variant*: reuses the existing Source-Derived Variance Check
     (read source, draft the all-six baseline, lock everything) except the
     "present to the human for confirmation" step is replaced by "lock
     immediately," and only the manifest-named dimension(s) are freshly
     decided rather than walked interactively.
   - Writes the spec to `docs/drafts/<story_name>/<story_name>-spec.md`;
     runs the existing cross-dimension consistency pass and self-resolves
     any contradiction found (documenting the resolution inline) instead
     of asking which side to revise.
2. **Autonomous planning** — a new "Autonomous Mode" section in
   `writing-story-plans`: identical mechanical process, minus the "show
   the plan, get sign-off" step. Self-checks the dimension carry-through
   table and per-chapter briefs against the spec and proceeds once
   internally consistent.
3. **Drafting** — `drafting-chapters`, unchanged: the same per-chapter
   `chapter-writer` subagent dispatch as interactive mode.
4. **Review-and-fix** — a new "Autonomous Mode" section in
   `reviewing-story-dimensions`: same `dimension-reviewer` subagent
   dispatch per chapter and once for the whole story, except "`Partial` →
   ask if unclear" becomes "`Partial` → treat as a gap and fix it, same as
   `Missing`" — a stricter default than interactive mode since there's no
   one to consult. Loops fix-and-re-review until every sub-dimension reads
   `Covered`.
5. **Promote** — copy `docs/drafts/<story_name>/` to
   `docs/stories/<story_name>/` once the whole-story review is fully
   clean.

All three "Autonomous Mode" additions are explicitly delimited sections
within the existing skill files, activated only when the orchestrator has
been told (via `batch-story-generation` / the batch system prompt) that
this is a batch run. Default interactive behavior — asking, waiting for
sign-off, asking about ambiguous `Partial`s — is untouched.

## Fix-loop safety bound

"Resolve everything, never promote something with unresolved findings" is
the target, but an autonomous loop needs a bounded escape valve so a run
can't hang forever. Per chapter: attempt 1 is an in-context fix pass,
attempt 2+ is a fresh `chapter-writer` redispatch that names the gap
explicitly (mirrors `drafting-chapters`' existing escalation logic) —
capped at 3 total attempts. If a chapter still isn't clean after that, the
*whole story* is abandoned rather than promoted with defects: its
`docs/drafts/<story_name>/` is left on disk as a record, and the batch
loop generates a fresh replacement story to still reach `--count`. This
should rarely trigger; it exists so the "nothing broken ever reaches
`docs/stories/`" guarantee holds even under a bound.

## Resume handling

On `psalm-saga-batch --session <id> --count N`:

1. Opens the existing session's checkpointer (same as interactive
   `--session` resume).
2. Counts existing `docs/stories/*` entries as already done; only
   generates the remainder needed to reach `N`.
3. Any unpromoted `docs/drafts/<name>/` left over from an interrupted run
   (crash/kill mid-pipeline) is treated as abandoned, same as a fix-loop
   failure — resuming a LangGraph thread mid-tool-call after a hard kill
   isn't reliable enough to trust, so the loop starts a fresh story rather
   than guessing where it left off.
4. An overall attempt cap (`count * 3`) stops the batch from spinning
   forever if something is systemically broken (e.g. an invalid API key);
   the CLI reports promoted vs. abandoned counts either way when it exits.

## Error handling

The existing reliability middleware (retry, rate limiting, token budget)
already covers transient per-call failures, unchanged. If an uncaught
exception escapes a per-story `agent.stream()` call, the CLI logs it,
leaves whatever is in `docs/drafts/<story_name>/` as an abandoned partial,
and continues to the next story attempt rather than crashing the whole
batch — subject to the same overall attempt cap as the fix-loop case
above.

## Testing

- Unit tests (`tests/unit/`) for the mechanical, non-model pieces: input
  path resolution (file vs. directory expansion), variant-manifest
  lookup/defaulting, `--combine` validation (rejecting `mixed` for
  `--mode variant`), draft-to-stories promotion/copy logic, and the
  resume/name-collision scan.
- End-to-end behavior of the new skill content (autonomous dimension
  decisions, self-resolved contradictions, fix-loop convergence) isn't
  unit-testable — it belongs in `tests/evals/` alongside the existing
  `test_psalm_saga.py` / `metrics.py` harness, exercising a small batch
  (1-2 stories) per mode.

## Open questions for implementation time

- Exact wording/placement of the "Autonomous Mode" sections within
  `story-brainstorming`, `writing-story-plans`, and
  `reviewing-story-dimensions` — drafted during implementation, reviewed
  the same way any skill edit is.
- Whether `_batch-log.md`'s diversity check needs anything more structured
  than a running prose log (e.g. a short tag per story) once real batches
  are run and diversity is evaluated in practice.
