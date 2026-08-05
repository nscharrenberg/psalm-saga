# Migrate story_bible.json patching to jsonpatchkit

## Problem

`update_story_bible` (`src/psalm_saga/tools/bible.py`) is the only tool subagents may use to
mutate `story_bible.json` — `write_file`/`edit_file` are permission-blocked on it
(`BIBLE_WRITE_PROTECTION`) precisely because earlier sessions showed models hand-authoring the
raw JSON text directly and corrupting it (duplicated keys, malformed nesting), then spiraling
into decoy files (`story_bible_cleaned.json`, `story_bible_v2.json`, ...) trying to recover.

`update_story_bible` itself is sound — it validates a patch against the `StoryBible` schema
before writing anything, so the file on disk can't become syntactically invalid through it. But
its patch format is a bespoke, hand-rolled merge-patch: the caller passes a partial object, which
is deep-merged key-by-key onto the existing document, with list fields (`characters`, `scenes`,
`themes`, `turning_points`) replaced wholesale because there's no generic "merge" for a list. That
means adding one character requires resending the entire `characters` array.

[jsonpatchkit](https://pypi.org/project/jsonpatchkit/) (the author's own library) implements RFC
6902 JSON Patch — `add`/`remove`/`replace`/`move`/`copy`/`test` operations addressed by RFC 6901
JSON Pointer paths — with Pydantic-schema validation built in. This spec migrates
`update_story_bible`/`validate_story_bible` onto it, replacing the bespoke merge-patch mechanism
with granular, standardized patch ops, and removing corruption-defense code that targeted a
failure mode the permission fix already closed off.

## Non-goals

- **No use of jsonpatchkit's `Extractor`/`ModelAdapter`/`LangChainAdapter`.** Those own the model
  call themselves (their own system prompt, their own two tools, their own retry loop) and are
  designed for single-shot, non-agentic extraction. `update_story_bible` is called mid-conversation
  by subagents that are already full ReAct agents with their own retry-via-conversation loop —
  layering jsonpatchkit's retry loop on top would duplicate that capability at the cost of a second
  LLM call on every single bible update, across four subagents that touch the bible repeatedly per
  session. Only jsonpatchkit's deterministic, non-LLM functions (`apply_patch`,
  `validate_against_schema`, the exception types) are used. If subagents turn out to struggle with
  authoring correct patches on their own turn once this ships, revisit with `Extractor` as a
  targeted addition then — not now, without evidence.
- **No change to `BIBLE_WRITE_PROTECTION`, subagent/orchestrator wiring, or any other tool.** This
  is scoped entirely to `tools/bible.py`, the prompts that document its patch format, and their
  tests.
- **No change to the `StoryBible` schema** (`dimensions.py`) or its business rules beyond how
  `mode` immutability is enforced (mechanism changes, behavior doesn't).

## Design

### Dependency

Add `jsonpatchkit` (core only — not the `[langchain]` extra) to `pyproject.toml`. Its only runtime
dependency is `pydantic>=2.13.4,<3.0`, which psalm-saga already satisfies exactly (`2.13.4`).

### `update_story_bible`

New signature:

```python
def update_story_bible(patch: list[JsonPatchOperation], reasoning: str = "") -> str
```

`JsonPatchOperation` is imported directly from `jsonpatchkit` (not redefined) — the model sees
jsonpatchkit's own field descriptions for `op`/`path`/`value`/`from` in the tool schema.
`reasoning` is optional and purely for the session transcript (mirrors jsonpatchkit's own
`PatchDocument.reasoning`); no logic depends on it.

Algorithm:

1. Read `story_bible.json`. If missing or not valid JSON, `current = {}` (see "Corrupt-file
   fallback" below).
2. **Bootstrap an empty document.** RFC 6902 `add`/`replace` require the parent container to
   already exist — you can't `replace /plot/structure` into `{}`, there's no `/plot` key. Every
   `StoryBible` field except `mode` has a schema default, so when `current` has no `mode` key yet,
   seed it with a full default skeleton (`StoryBible.model_construct(mode=<placeholder>).model_dump()`,
   `mode` immediately overwritten by the incoming patch) before applying the patch. This means even
   the very first `update_story_bible` call of a session can use granular per-field ops
   (`{"op": "replace", "path": "/plot/structure", "value": "..."}`) — no special-casing needed for
   "first call vs. later calls." Because every successful write serializes the full validated model
   (step 6), the file on disk is always fully skeleton-shaped after the first successful call, so
   this bootstrap path is only ever exercised once per session.
3. Apply the patch: `apply_patch(current, [op.model_dump(by_alias=True, exclude_none=True) for op
   in patch])`. On `UnknownOperationError`, `MalformedOperationError`, `PatchTestFailedError`,
   `PointerSyntaxError`, or `PointerResolutionError` (all `jsonpatchkit.exceptions`), return
   `f"Patch rejected -- story_bible.json was NOT changed.\n{exc}"` — nothing written. These
   exceptions are already written to be LLM-retry-friendly per jsonpatchkit's own docstrings.
4. Validate: `validate_against_schema(patched, StoryBible)`. If invalid, return
   `f"Patch rejected -- story_bible.json was NOT changed.\n{format_errors_for_retry_prompt(outcome.errors)}"`
   — nothing written.
5. **Mode immutability** (psalm-saga-specific, not jsonpatchkit's concern): if the bible already
   existed with a `mode` set, and `outcome.validated.mode` differs from the pre-patch `mode`,
   reject the whole patch with the same message as today. Checked by comparing the validated
   result's `mode` to the pre-patch `mode` directly (not by inspecting the raw op list), so it
   can't be bypassed via `move`/`copy` ops targeting `/mode` indirectly.
6. Write `outcome.validated.model_dump_json(indent=2)` to `story_bible.json` — unchanged from
   today. Reset the (surviving, non-escalation) validation-failure bookkeeping if any remains — see
   "Corrupt-file fallback" below for what's kept.
7. Return `f"OK: story_bible.json updated ({status})."` via `is_ready_for_writing()` — unchanged
   from today, minus the `recovered_note`/`recovering_from_corruption` ceremony.

### `validate_story_bible`

Keeps its core role — JSON-parseable? → schema-valid? → readiness (missing/empty required fields)
report — via `validate_against_schema` instead of a manual `try/except ValidationError`. The
failure-counter/escalation mechanism (`_bump_failure_counter`, `_ESCALATION_THRESHOLD`, the
"3 strikes, STOP hand-editing" message) is removed entirely: it targeted repeated hand-edited JSON
corruption, which is no longer reachable now that `update_story_bible` is the only writer and
validates before every write. A corrupt-on-disk file now just reports
`"story_bible.json is not valid JSON: {parse error}"` with no counter and no escalation.

### Corrupt-file fallback

`update_story_bible` keeps a minimal fallback for an unreadable/corrupt file on disk (e.g. a
session created before this migration): treat it as `current = {}` and proceed via the bootstrap
path in step 2. No escalation messaging, no `"recovered from a corrupt file on disk"` note in the
return value — it's just the empty-document case, indistinguishable from a brand-new bible.

### List-field ops and the `test` mitigation

Today, list fields are always resent wholesale — clunky, but immune to drift. RFC 6902 array ops
are index-based (`/characters/2`), so a `remove` or `replace` at a stale index is a real failure
mode if a model's idea of current list state has drifted. jsonpatchkit's `test` op is the built-in
mitigation and is the recommended pattern in the rewritten prompts: prefix an index-based
`remove`/`replace` with a `test` op asserting the expected current value, so drift surfaces as a
clear, retryable `PatchTestFailedError` instead of silently mutating the wrong element. Appends
(`add` at `/characters/-`) are unaffected — always safe regardless of current length.

### Prompt changes

`extractor.md`, `brainstorm.md`, `originality_guard.md`, and `editor.md` currently document the
old merge-patch contract ("pass a partial object, it's deep-merged, lists are replaced wholesale")
and get rewritten to teach: RFC 6902 op syntax, JSON Pointer path syntax, `/field/-` for list
append, and the test-before-index-op convention above. The existing advice to split large patches
into a few calls stays (and reads more naturally now that ops are already granular).
`psalm_dimensions_reference.md`'s mention of `update_story_bible` is format-agnostic ("all changes
... go through the `update_story_bible` tool ... which validates a patch before writing") and
needs no change.

## Error handling

- **Bad op shape** (unknown `op`, missing `value`/`from`): `MalformedOperationError`/
  `UnknownOperationError` from `apply_patch`, surfaced verbatim, nothing written.
- **Bad path**: `PointerSyntaxError` (malformed pointer) or `PointerResolutionError` (doesn't
  resolve — e.g. `add` into a nonexistent parent, `remove` on nothing), surfaced verbatim, nothing
  written.
- **Stale `test` assertion**: `PatchTestFailedError`, surfaced verbatim, nothing written — this is
  the expected, retryable signal for list-index drift described above.
- **Schema violation after a structurally valid patch**: `validate_against_schema` failure,
  rendered via `format_errors_for_retry_prompt`, nothing written.
- **`mode` change attempted**: rejected with the existing message, nothing written.
- **Corrupt/missing file on disk**: falls back to `current = {}`, no error surfaced — same as a
  brand-new bible.

## Testing

No live model calls, consistent with the rest of the suite:

- `tests/test_update_story_bible.py` (currently dict-patch-based) is rewritten to the op-list API,
  keeping equivalent coverage: replace-one-field-sibling-untouched (was
  merge-without-clobbering), append-via-`/-` (was list-replaced-wholesale), invalid-patch-rejected-
  and-file-untouched, mode-immutability, corrupt-file-on-disk falls back to empty. New cases:
  `PatchTestFailedError` from a stale-index `test` op, `PointerResolutionError` from a bad path,
  bootstrap-from-empty produces a full skeleton after the first successful call so the second call
  can use a granular op immediately.
- `tests/test_bible_tool.py` (currently exercises `validate_story_bible`'s escalation ladder) drops
  the escalation-specific tests (`test_validate_escalates_after_repeated_invalid_json`,
  `test_validate_failure_counter_resets_after_success`) and keeps the rest, adjusted for
  `validate_against_schema`-backed error formatting.
- `tests/test_bible_write_protection.py` is untouched — it tests `write_file`/`edit_file` blocking,
  which is independent of the patch format.
