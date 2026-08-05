# Story Bible jsonpatchkit Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `update_story_bible`'s bespoke merge-patch mechanism with jsonpatchkit's RFC 6902 JSON Patch (`apply_patch` + `validate_against_schema`), so patches are granular (list append without resending the whole list) and the bible's corruption-defense code that targeted a now-closed failure mode is removed.

**Architecture:** `src/psalm_saga/tools/bible.py`'s two tools (`update_story_bible`, `validate_story_bible`) are rewritten to consume/apply RFC 6902 ops instead of hand-rolled deep-merge dicts, using jsonpatchkit's deterministic (non-LLM) functions only. Four subagent prompts that document the old patch format are rewritten to teach the new one. No other file in the codebase changes.

**Tech Stack:** Python, Pydantic, `jsonpatchkit` (already added to `pyproject.toml`/`uv.lock` — not yet committed), `langchain_core.tools.tool`, pytest.

## Global Constraints

- `jsonpatchkit`'s only runtime dependency is `pydantic>=2.13.4,<3.0`; psalm-saga is pinned to `2.13.4` exactly — no version conflict, verify no other pin changes.
- Only jsonpatchkit's deterministic functions are used: `apply_patch`, `validate_against_schema`, `JsonPatchOperation`, `JsonPatchKitError` and its subclasses, `format_errors_for_retry_prompt`. Never import or use `Extractor`, `ModelAdapter`, or `LangChainAdapter` (see spec's Non-goals — those own their own model call and would duplicate the subagents' existing retry-via-conversation loop at the cost of a second LLM call per bible update).
- `format_errors_for_retry_prompt` and `ValidationOutcome` are **not** re-exported from the top-level `jsonpatchkit` package — import them from `jsonpatchkit.validation`. Everything else used in this plan (`apply_patch`, `validate_against_schema`, `JsonPatchOperation`, `JsonPatchKitError`) imports from the top-level `jsonpatchkit` package.
- Do not modify `BIBLE_WRITE_PROTECTION`, subagent/orchestrator wiring, or the `StoryBible` schema (`dimensions.py`) — out of scope per the spec's Non-goals.
- No live model calls in any test — this codebase's whole test suite runs without one; keep it that way.

---

## Task 1: Commit the outstanding write-protection fix

This is prep, not new work: `pyproject.toml`, `orchestrator.py`, `subagents.py`, `tools/__init__.py`, `tools/bible.py`, and `tests/test_bible_write_protection.py` already have an uncommitted, fully-tested fix from a prior session (`BIBLE_WRITE_PROTECTION`, blocking `write_file`/`edit_file` on `story_bible.json`). Task 2 modifies `tools/bible.py` further — committing this first keeps that diff clean instead of conflating two unrelated changes. The `jsonpatchkit` line already present in `pyproject.toml`/`uv.lock` is a *different* concern (added ahead of this migration) and is deliberately left uncommitted here — it belongs with Task 2, the task that actually uses it.

**Files:**
- Commit (already modified, no further edits in this task): `src/psalm_saga/agents/orchestrator.py`, `src/psalm_saga/agents/subagents.py`, `src/psalm_saga/tools/__init__.py`, `src/psalm_saga/tools/bible.py`
- Commit (already created, no further edits): `tests/test_bible_write_protection.py`
- Leave uncommitted: `pyproject.toml`, `uv.lock` (the `jsonpatchkit` dependency addition — Task 2 commits these)

**Interfaces:** N/A — no code changes in this task, only a commit boundary.

- [ ] **Step 1: Verify the existing fix still passes before committing it**

Run: `uv run pytest tests/test_bible_write_protection.py -v`
Expected: `2 passed`

- [ ] **Step 2: Stage exactly the write-protection files (not pyproject.toml/uv.lock)**

```bash
git add src/psalm_saga/agents/orchestrator.py src/psalm_saga/agents/subagents.py src/psalm_saga/tools/__init__.py src/psalm_saga/tools/bible.py tests/test_bible_write_protection.py
git status
```

Confirm the status output shows only those five files staged, and `pyproject.toml`/`uv.lock` still listed as unstaged modifications.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(bible): block write_file/edit_file on story_bible.json

FilesystemMiddleware is attached to every subagent unconditionally by
deepagents' create_deep_agent, regardless of a SubAgent's own tools list --
so omitting write_file/edit_file from a subagent's tools does not stop it
from getting them via middleware. Add a FilesystemPermission rule denying
writes to story_bible.json (and lookalikes), forcing all bible mutations
through update_story_bible, which validates before writing.
EOF
)"
```

---

## Task 2: Rewrite `tools/bible.py` on jsonpatchkit

**Files:**
- Modify: `src/psalm_saga/tools/bible.py`
- Modify: `pyproject.toml`, `uv.lock` (already have the `jsonpatchkit` addition uncommitted — this task commits them)
- Test: `tests/test_update_story_bible.py` (full rewrite)
- Test: `tests/test_bible_tool.py` (full rewrite)

**Interfaces:**
- Produces: `make_update_story_bible_tool(session_dir: Path)` returns a tool whose function signature is `update_story_bible(patch: list[JsonPatchOperation], reasoning: str = "") -> str`. `make_validate_bible_tool(session_dir: Path)` returns a tool `validate_story_bible() -> str`. Both unchanged in name/factory signature from before this task — only the `update_story_bible` tool function's `patch` parameter type changes (was `dict[str, Any]`, now `list[JsonPatchOperation]`). `BIBLE_FILENAME`, `BIBLE_WRITE_PROTECTION`, `load_bible`, `bible_path` (module-level function) are unchanged and still exported from `psalm_saga.tools` — do not touch `tools/__init__.py` in this task, its exports already cover everything this task needs.
- Consumes: `StoryBible`, `GenerationMode` from `psalm_saga.dimensions` (unchanged schema). `apply_patch`, `validate_against_schema`, `JsonPatchOperation`, `JsonPatchKitError` from `jsonpatchkit`; `format_errors_for_retry_prompt` from `jsonpatchkit.validation`.

### Step 1: Write the failing test — `tests/test_update_story_bible.py`

Replace the entire file:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psalm_saga.dimensions import GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.bible import make_update_story_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def _op(op: str, path: str, value: Any = None, **kw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"op": op, "path": path}
    if value is not None:
        payload["value"] = value
    payload.update(kw)
    return payload


def test_creates_bible_from_scratch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    patch = [
        _op("replace", "/mode", "from_scratch"),
        _op("replace", "/premise", "A lighthouse keeper."),
    ]
    result = _invoke(tool, patch=patch)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    on_disk = json.loads((tmp_path / "story_bible.json").read_text())
    assert on_disk["mode"] == "from_scratch"
    assert on_disk["premise"] == "A lighthouse keeper."


def test_replace_one_field_leaves_sibling_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/plot/structure", "three-act"),
        ],
    )
    _invoke(tool, patch=[_op("replace", "/plot/climax", "The light goes out for good.")])  # type: ignore[no-untyped-call]

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.plot.structure == "three-act"
    assert bible.plot.climax == "The light goes out for good."


def test_append_to_a_list_via_dash_path(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
        ],
    )
    _invoke(tool, patch=[_op("add", "/characters/-", {"name": "Odile", "role": "antagonist"})])  # type: ignore[no-untyped-call]

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert [c.name for c in bible.characters] == ["Mara", "Odile"]


def test_invalid_patch_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("replace", "/mode", "from_scratch"), _op("replace", "/premise", "A lighthouse keeper.")],
    )
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(tool, patch=[_op("replace", "/mode", "not_a_real_mode")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_mode_cannot_be_changed_by_a_patch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("replace", "/mode", "from_scratch"), _op("replace", "/premise", "A lighthouse keeper.")],
    )

    result = _invoke(tool, patch=[_op("replace", "/mode", "from_source")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert "cannot be changed" in result

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.mode is GenerationMode.FROM_SCRATCH


def test_recovers_from_corrupt_file_on_disk(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json at all")
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("replace", "/mode", "from_scratch"), _op("replace", "/premise", "A fresh start.")],
    )
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.premise == "A fresh start."


def test_stale_index_test_op_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
        ],
    )
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("test", "/characters/0/name", "SomeoneElse"),
            _op("remove", "/characters/0"),
        ],
    )
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_bad_path_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch=[_op("replace", "/mode", "from_scratch")])  # type: ignore[no-untyped-call]
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(tool, patch=[_op("replace", "/nonexistent/field", "x")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_first_call_bootstraps_a_full_skeleton_for_granular_second_call(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch=[_op("replace", "/mode", "from_scratch")])  # type: ignore[no-untyped-call]

    # Only possible if the first call's write already produced a full schema-shaped skeleton on
    # disk (every StoryBible field present with its default), not just the one key the first
    # patch explicitly touched.
    result = _invoke(tool, patch=[_op("replace", "/plot/structure", "three-act")])  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.plot.structure == "three-act"
```

### Step 2: Run it to verify it fails

Run: `uv run pytest tests/test_update_story_bible.py -v`
Expected: `FAIL` — `TypeError` or `ValidationError` from the old `update_story_bible(patch: dict[str, Any])` rejecting a `list` argument (`patch=[...]` no longer matches the current dict-based signature).

### Step 3: Write the failing test — `tests/test_bible_tool.py`

Replace the entire file:

```python
from pathlib import Path

from psalm_saga.dimensions import Character, GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.bible import make_validate_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def test_validate_reports_missing_file(tmp_path: Path) -> None:
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "does not exist yet" in result


def test_validate_reports_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json")
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "Invalid JSON" in result


def test_validate_reports_schema_errors(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text('{"mode": "not_a_real_mode"}')
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "Schema errors" in result


def test_validate_reports_missing_required_fields(tmp_path: Path) -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "not yet ready" in result
    assert "premise" in result


def test_validate_reports_ok_when_ready(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A clockmaker starts losing time itself, one hour at a time.",
        characters=[Character(name="Odile", role="protagonist")],
    )
    bible.plot.structure = "three-act"
    bible.plot.inciting_incident = "Odile's shop clock strikes an hour that hasn't happened yet."
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK: story_bible.json is schema-valid and has the minimum fields")


def test_validate_does_not_escalate_after_repeated_invalid_json(tmp_path: Path) -> None:
    """Regression test for removing the failure-counter escalation ladder: repeated calls
    against the same broken file must stay flat (same plain message every time), not build up
    to a 'STOP hand-editing' message -- that mechanism targeted a corruption path that no longer
    exists now that update_story_bible is the only writer and validates before every write."""
    (tmp_path / "story_bible.json").write_text("{not valid json")
    tool = make_validate_bible_tool(tmp_path)

    for _ in range(5):
        result = _invoke(tool)  # type: ignore[no-untyped-call]
        assert "STOP" not in result
        assert "Invalid JSON" in result
```

### Step 4: Run it to verify it fails

Run: `uv run pytest tests/test_bible_tool.py -v`
Expected: `test_validate_does_not_escalate_after_repeated_invalid_json` FAILs (the current code escalates on the 3rd call, so `"STOP"` appears in the loop). The other five tests pass unchanged (they don't depend on the rewrite).

### Step 5: Implement — rewrite `src/psalm_saga/tools/bible.py`

Replace the entire file:

```python
"""Deterministic helpers for reading/validating ``story_bible.json``.

Agents mutate the bible exclusively through ``update_story_bible``, which applies an RFC 6902
JSON Patch (via jsonpatchkit) and validates the result against :class:`StoryBible` before writing
anything -- the file on disk can never end up syntactically broken or schema-invalid by going
through it. ``write_file``/``edit_file`` are permission-blocked on it (see
``BIBLE_WRITE_PROTECTION``) as a second line of defense.
"""

import json
from pathlib import Path
from typing import Any

from deepagents.middleware.filesystem import FilesystemPermission
from jsonpatchkit import JsonPatchKitError, JsonPatchOperation, apply_patch, validate_against_schema
from jsonpatchkit.validation import format_errors_for_retry_prompt
from langchain_core.tools import tool

from psalm_saga.dimensions import GenerationMode, StoryBible

BIBLE_FILENAME = "story_bible.json"

BIBLE_WRITE_PROTECTION: list[FilesystemPermission] = [
    FilesystemPermission(operations=["write"], paths=["/story_bible*.json"], mode="deny"),
]
"""Blocks the built-in ``write_file``/``edit_file`` tools from touching story_bible.json
(or lookalikes like story_bible_v2.json / story_bible_cleaned.json).

``FilesystemMiddleware`` is attached to every subagent unconditionally by deepagents'
``create_deep_agent``, regardless of what a SubAgent's own ``tools`` list contains -- so
merely omitting write_file/edit_file from a subagent's tools does NOT stop it from getting
them via middleware. Without this rule, a model can (and in practice does) hand-author or
hand-edit the bible's raw JSON text instead of going through ``update_story_bible``,
producing syntactically invalid JSON that ``update_story_bible``'s validate-before-write
step would have caught. Pass this to every agent that can see story_bible.json.
"""


def _bootstrap_skeleton() -> dict[str, Any]:
    """A full StoryBible skeleton (every field at its schema default) with a placeholder
    ``mode``, so a brand-new document already has every container key an RFC 6902 op could
    target. The incoming patch's own mode op overwrites the placeholder immediately after this
    is merged in -- see ``make_update_story_bible_tool``.
    """
    return StoryBible.model_construct(mode=GenerationMode.FROM_SCRATCH).model_dump(mode="json")


def make_update_story_bible_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build an ``update_story_bible`` tool bound to one session's bible file."""
    bible_path = session_dir / BIBLE_FILENAME

    @tool
    def update_story_bible(patch: list[JsonPatchOperation], reasoning: str = "") -> str:
        """Apply an RFC 6902 JSON Patch to story_bible.json and validate the result before writing.

        ALWAYS use this to change story_bible.json -- never write_file or edit_file on it
        directly (both are permission-blocked on it anyway), and never create a different file
        for it (no story_bible_cleaned.json, story_bible_v2.json, etc.). This tool applies and
        validates the patch itself, so the file on disk can never end up syntactically broken or
        schema-invalid by going through it.

        Each entry in `patch` is one operation: `{"op": "replace", "path": "/plot/structure",
        "value": "three-act"}` sets a field that already exists -- every StoryBible field has a
        schema default, so `replace` always works, even on your very first call of a session.
        Use `"add"` with a path ending in `/-` to append to a list, e.g. `{"op": "add", "path":
        "/characters/-", "value": {"name": "Finn", "role": "..."}}`. Use `"remove"` to delete a
        list entry or clear a dict key. Before a `remove` or index-targeted `replace` on a list
        (e.g. `/characters/2`), prefix it with a `"test"` op asserting the value you expect to be
        there -- if the list has drifted since you last read it, the test fails with a clear,
        retryable error instead of silently mutating the wrong entry.

        If the patch would produce an invalid bible, nothing is written -- you get back the
        specific error to fix in your next call.

        Args:
            patch: A list of RFC 6902 JSON Patch operations to apply, in order.
            reasoning: Optional short note on why you're making this change (for the session log
                only; not validated or acted on).
        """
        current: dict[str, Any] = {}
        if bible_path.exists():
            try:
                current = json.loads(bible_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}

        pre_patch_mode = current.get("mode")
        if "mode" not in current:
            current = _bootstrap_skeleton() | current

        try:
            patched = apply_patch(
                current,
                [op.model_dump(by_alias=True, exclude_none=True) for op in patch],
            )
        except JsonPatchKitError as exc:
            return f"Patch rejected -- story_bible.json was NOT changed.\n{exc}"

        outcome = validate_against_schema(patched, StoryBible)
        if not outcome.is_valid:
            return (
                "Patch rejected -- story_bible.json was NOT changed.\n"
                f"{format_errors_for_retry_prompt(outcome.errors)}"
            )

        bible = outcome.validated
        if pre_patch_mode is not None and bible.mode != pre_patch_mode:
            return (
                f"Rejected -- story_bible.json was NOT changed. 'mode' is fixed for this "
                f"session ({pre_patch_mode!r}) and cannot be changed by a patch."
            )

        bible_path.write_text(bible.model_dump_json(indent=2), encoding="utf-8")

        ready, missing = bible.is_ready_for_writing()
        status = "ready for the writer subagent" if ready else f"missing: {', '.join(missing)}"
        return f"OK: story_bible.json updated ({status})."

    return update_story_bible


def make_validate_bible_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a ``validate_story_bible`` tool bound to one session's bible file.

    This is a read-only reporting tool -- unlike ``update_story_bible`` it can't fix anything, it
    just tells you what's wrong (or what's still missing for the writer subagent).

    Args:
        session_dir: The session directory (also the root of the FilesystemBackend), so the
            tool reads the same file the agent's ``read_file``/``write_file`` tools operate on.
    """
    bible_path = session_dir / BIBLE_FILENAME

    @tool
    def validate_story_bible() -> str:
        """Validate story_bible.json against the PSALM-SAGA schema and report any errors.

        Call this after updating story_bible.json, and again right before handing off to the
        writer subagent. Returns "OK" plus a summary of missing-but-recommended fields, or a
        precise list of schema errors to fix. This tool only reports, it never repairs -- fix
        anything it flags via update_story_bible.
        """
        if not bible_path.exists():
            return (
                f"{BIBLE_FILENAME} does not exist yet. Create it with update_story_bible "
                "(pass the initial fields as a patch), not write_file."
            )

        raw = bible_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"Invalid JSON in {BIBLE_FILENAME}: {exc}"

        outcome = validate_against_schema(data, StoryBible)
        if not outcome.is_valid:
            return (
                f"Schema errors in {BIBLE_FILENAME} (valid JSON, but doesn't match the Story "
                f"Bible schema):\n{format_errors_for_retry_prompt(outcome.errors)}\n\nFix via "
                "update_story_bible with a patch for the offending field(s)."
            )

        bible = outcome.validated
        ready, missing = bible.is_ready_for_writing()
        if ready:
            return "OK: story_bible.json is schema-valid and has the minimum fields for writing."
        return (
            "OK: story_bible.json is schema-valid, but not yet ready for the writer subagent. "
            f"Missing/empty required fields: {', '.join(missing)}."
        )

    return validate_story_bible


def load_bible(session_dir: Path) -> StoryBible:
    """
    Loads the Bible data from a JSON file stored in the session directory. The JSON file
    is expected to have a structure that matches the StoryBible model.

    :param session_dir: A path to the session directory containing the Bible JSON file.
    :type session_dir: Path
    :return: An instance of the StoryBible model populated with data from the JSON file.
    :rtype: StoryBible
    """
    path = session_dir / BIBLE_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    return StoryBible.model_validate(data)


def bible_path(session_dir: Path) -> Path:
    """
    Constructs the path to the Bible file within the given session directory.

    This function is used to generate the full file path for the Bible file
    by combining the session directory with the pre-defined file name.

    :param session_dir: The directory path where the Bible file is stored. Must
        be a valid `Path` object.
    :return: The complete path to the Bible file as a `Path` object.
    """
    return session_dir / BIBLE_FILENAME
```

### Step 6: Run tests to verify they pass

Run: `uv run pytest tests/test_update_story_bible.py tests/test_bible_tool.py tests/test_bible_write_protection.py -v`
Expected: all `PASS`. (`test_bible_write_protection.py` is included as a regression check — it's untouched by this task but shares the file.)

### Step 7: Run the full suite and lint to catch anything relying on removed internals

```bash
uv run pytest -q
uv run ruff check src/psalm_saga/tools/bible.py tests/test_update_story_bible.py tests/test_bible_tool.py
```

Expected: full suite passes; ruff reports no new issues introduced by this task (pre-existing unrelated `E501`s elsewhere in the repo are not this task's concern).

### Step 8: Commit

```bash
git add pyproject.toml uv.lock src/psalm_saga/tools/bible.py tests/test_update_story_bible.py tests/test_bible_tool.py
git commit -m "$(cat <<'EOF'
refactor(bible): migrate update_story_bible to jsonpatchkit RFC 6902 patches

Replaces the hand-rolled deep-merge dict patch format with jsonpatchkit's
apply_patch + validate_against_schema, so list fields (characters, scenes,
themes, turning_points) can be appended to granularly instead of resent
wholesale on every change. Also drops validate_story_bible's failure-counter
escalation ladder -- it targeted repeated hand-edited JSON corruption, which
is no longer reachable now that update_story_bible is the only writer and
validates before every write.
EOF
)"
```

---

## Task 3: Rewrite subagent prompts to teach RFC 6902 patch syntax

**Files:**
- Modify: `src/psalm_saga/prompts/extractor.md`
- Modify: `src/psalm_saga/prompts/brainstorm.md`
- Modify: `src/psalm_saga/prompts/originality_guard.md`
- Modify: `src/psalm_saga/prompts/editor.md`
- Test: `tests/test_prompts.py` (new)
- No change: `src/psalm_saga/prompts/psalm_dimensions_reference.md` (its one mention of `update_story_bible` — "all changes to `story_bible.json` go through the `update_story_bible` tool ... which validates a patch before writing" — is already format-agnostic)

**Interfaces:**
- Consumes: `load_prompt(name: str) -> str` from `psalm_saga.prompts` (unchanged).
- Produces: nothing new — this task only changes prompt file contents, not any Python interface.

### Step 1: Write the failing test — `tests/test_prompts.py`

Create the file:

```python
from psalm_saga.prompts import load_prompt  # type: ignore[import-untyped]


def test_extractor_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("extractor")
    assert '"op": "replace"' in text
    assert '"op": "add"' in text
    assert "deep-merged" not in text


def test_brainstorm_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("brainstorm")
    assert '"op": "replace"' in text
    assert '"op": "test"' in text
    assert "replaced wholesale" not in text


def test_originality_guard_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("originality_guard")
    assert '"op": "add"' in text
    assert "replaces the field wholesale" not in text


def test_editor_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("editor")
    assert '"op": "add"' in text
    assert "pass the complete list" not in text
```

### Step 2: Run it to verify it fails

Run: `uv run pytest tests/test_prompts.py -v`
Expected: all four `FAIL` (none of the prompts mention `"op":` yet; the old-format phrases are still present).

### Step 3: Rewrite `src/psalm_saga/prompts/extractor.md`

In the numbered process list, replace step 5 (currently: `5. Call \`update_story_bible\` with everything you've extracted as one patch (\`mode: "from_source"\` and \`source_excerpt_path\` set to the source file's path, plus all six dimensions) -- never \`write_file\`/\`edit_file\` on \`story_bible.json\` directly, and never create any other file for it (no \`story_bible_cleaned.json\` etc.). If the patch is large, splitting it into a few \`update_story_bible\` calls (e.g. core fields first, then \`characters\`, then the rest) is fine and often easier to get right than one huge call. Call \`validate_story_bible\` afterward and fix any reported errors via another \`update_story_bible\` patch before finishing.`) with:

```markdown
5. Call `update_story_bible` with what you've extracted, as a list of RFC 6902 JSON Patch
   operations -- `{"op": "replace", "path": "/mode", "value": "from_source"}`,
   `{"op": "replace", "path": "/source_excerpt_path", "value": "..."}`, one `replace` per
   scalar/object field (`/premise`, `/plot/structure`, `/writing_style/tone/value`, etc.), and one
   `{"op": "add", "path": "/characters/-", "value": {...}}` per character (same pattern for
   `scenes`, `themes`, `turning_points`). Never `write_file`/`edit_file` on `story_bible.json`
   directly, and never create any other file for it (no `story_bible_cleaned.json` etc.). A whole
   extraction is naturally a lot of ops -- splitting them into a few `update_story_bible` calls
   (e.g. core fields first, then all `characters` adds, then the rest) is fine and often easier to
   get right than one huge call. Call `validate_story_bible` afterward and fix any reported errors
   via another `update_story_bible` patch before finishing.
```

### Step 4: Rewrite `src/psalm_saga/prompts/brainstorm.md`

Under "Ground rules", replace the bullet (currently: `- Read \`story_bible.json\` at the start of every turn (things may have changed, e.g. after the originality guard sent it back with findings) and call \`update_story_bible\` with each new answer as soon as you have it, rather than accumulating everything in memory until the end. Never use \`write_file\`/\`edit_file\` on \`story_bible.json\` directly, and never create any other file for it (no \`story_bible_cleaned.json\`, \`story_bible_v2.json\`, etc.) -- \`update_story_bible\` is the only way this file should change, and it always targets \`story_bible.json\` itself.`) with this bullet plus a new one immediately after it:

```markdown
- Read `story_bible.json` at the start of every turn (things may have changed, e.g. after the
  originality guard sent it back with findings) and call `update_story_bible` with each new
  answer as soon as you have it, rather than accumulating everything in memory until the end.
  Never use `write_file`/`edit_file` on `story_bible.json` directly, and never create any other
  file for it (no `story_bible_cleaned.json`, `story_bible_v2.json`, etc.) -- `update_story_bible`
  is the only way this file should change, and it always targets `story_bible.json` itself.
- Patches to `update_story_bible` are a list of RFC 6902 JSON Patch operations, not a whole
  object. Use `{"op": "replace", "path": "/writing_style/tone/value", "value": "..."}` (plus a
  paired op setting `.../settled` to `true` once the user confirms) for a single field -- every
  field already exists with a schema default, so `replace` always works, even on your very first
  call of a session. Use `{"op": "add", "path": "/characters/-", "value": {...}}` to add a new
  character (same `/-` pattern for `scenes`, `themes`, `turning_points`); use `"remove"` to drop
  one. Before removing or replacing a specific list entry by index (e.g. `/characters/2`), prefix
  it with a `{"op": "test", "path": "/characters/2/name", "value": "..."}` asserting what you
  expect there, so a stale index fails loudly instead of silently touching the wrong entry.
```

Then, in the "If invoked to negotiate a divergence plan" section, replace the sentence (currently: `Call \`update_story_bible\` with the confirmed result as \`divergence_plan.per_dimension\` (every dimension must end up with a level -- an incomplete plan can't be checked for fidelity later).`) with:

```markdown
Call `update_story_bible` with the confirmed result, one `{"op": "replace", "path":
"/divergence_plan/per_dimension/<dimension>", "value": "<level>"}` op per dimension (every
dimension must end up with a level -- an incomplete plan can't be checked for fidelity later).
```

### Step 5: Rewrite `src/psalm_saga/prompts/originality_guard.md`

Replace the paragraph (currently: `\`originality_findings\` is a list field, so pass the *complete* list (all findings, old and new) in your \`update_story_bible\` patch -- it replaces the field wholesale, it doesn't append. Never use \`write_file\`/\`edit_file\` on \`story_bible.json\` directly, and never create any other file for it.`) with:

```markdown
Append each new finding with `{"op": "add", "path": "/originality_findings/-", "value": {...}}`.
When flipping an existing finding to `resolved: true` after a revision, target it directly --
`{"op": "replace", "path": "/originality_findings/<index>/resolved", "value": true}` (read the
current list first via `story_bible.json` so you know the right index; prefix with a `{"op":
"test", "path": "/originality_findings/<index>/category", "value": "..."}` op if you want to
guard against it having moved). Never use `write_file`/`edit_file` on `story_bible.json` directly,
and never create any other file for it.
```

### Step 6: Rewrite `src/psalm_saga/prompts/editor.md`

Replace the sentence in the fidelity self-check section (currently: `Write your assessment to \`story_bible.json\`'s \`achieved_divergence\` field (one entry per dimension) via \`update_story_bible\`, then call \`check_fidelity_alignment\` and include its result verbatim in your final message.`) with:

```markdown
Write your assessment to `story_bible.json`'s `achieved_divergence` field via `update_story_bible`
-- one `{"op": "add", "path": "/achieved_divergence/<dimension>", "value": "<level>"}` op per
dimension (`achieved_divergence` starts empty, so `add` is what introduces each key; a later
correction to an already-set dimension can use `add` again, it upserts) -- then call
`check_fidelity_alignment` and include its result verbatim in your final message.
```

Then replace the paragraph near the end (currently: `Write the final text to \`final_story.md\`. If from_scratch mode and you find something copyright- adjacent that the originality guard didn't catch, call \`update_story_bible\` to add an \`OriginalityFinding\` to \`story_bible.json\` (category \`other\`, note that it was caught at the editing stage; \`originality_findings\` is a list field, so pass the complete list including the existing findings, not just the new one) rather than silently rewriting around it -- the orchestrator and user should know it happened. Never use \`write_file\`/\`edit_file\` on \`story_bible.json\` directly, and never create any other file for it.`) with:

```markdown
Write the final text to `final_story.md`. If from_scratch mode and you find something copyright-
adjacent that the originality guard didn't catch, call `update_story_bible` to append an
`OriginalityFinding` to `story_bible.json` (`{"op": "add", "path": "/originality_findings/-",
"value": {"category": "other", ...}}`, noting that it was caught at the editing stage) rather than
silently rewriting around it -- the orchestrator and user should know it happened. Never use
`write_file`/`edit_file` on `story_bible.json` directly, and never create any other file for it.
```

### Step 7: Run tests to verify they pass

Run: `uv run pytest tests/test_prompts.py -v`
Expected: all four `PASS`.

### Step 8: Commit

```bash
git add src/psalm_saga/prompts/extractor.md src/psalm_saga/prompts/brainstorm.md src/psalm_saga/prompts/originality_guard.md src/psalm_saga/prompts/editor.md tests/test_prompts.py
git commit -m "$(cat <<'EOF'
docs(prompts): teach RFC 6902 patch syntax for update_story_bible

extractor.md, brainstorm.md, originality_guard.md, and editor.md documented
the old merge-patch dict contract (partial object, deep-merged, lists
replaced wholesale). Rewrite each to teach JSON Patch ops -- replace for
existing fields, add at /field/- for list append, test before an
index-targeted remove/replace to guard against stale indices.
EOF
)"
```

---

## Task 4: Full-suite verification

**Files:** none modified — verification only.

**Interfaces:** N/A.

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`
Expected: all tests pass, including `test_bible_write_protection.py` (unrelated to the patch-format change, should be unaffected), `test_update_story_bible.py`, `test_bible_tool.py`, and `test_prompts.py` from this plan.

- [ ] **Step 2: Run ruff across the full touched surface**

Run: `uv run ruff check src/psalm_saga/tools/bible.py src/psalm_saga/agents/subagents.py src/psalm_saga/agents/orchestrator.py src/psalm_saga/tools/__init__.py tests/test_update_story_bible.py tests/test_bible_tool.py tests/test_prompts.py tests/test_bible_write_protection.py`
Expected: no new issues (pre-existing unrelated `E501`s elsewhere in `subagents.py`/`orchestrator.py`/`bible.py` predate this plan and are out of scope).

- [ ] **Step 3: Confirm the dependency line is exactly as expected**

Run: `grep -n "jsonpatchkit" pyproject.toml`
Expected: `"jsonpatchkit>=0.1.0",` present under `dependencies`, no `[langchain]` extra.

- [ ] **Step 4: Confirm git status is clean**

Run: `git status`
Expected: working tree clean, all four commits from Tasks 1-3 present in `git log --oneline -4`.
