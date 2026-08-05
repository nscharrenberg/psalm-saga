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
        "value": "three-act"}` sets a field that already exists -- most StoryBible fields already
        exist with a schema default, so `replace` works for them from your first call. A field
        that's `None`/empty until first set (like `mode` on your very first call of a session, or
        a new key inside a dict field such as `/achieved_divergence/<dimension>`) needs `"add"`
        instead. Use `"add"` with a path ending in `/-` to append to a list, e.g. `{"op": "add",
        "path": "/characters/-", "value": {"name": "Finn", "role": "..."}}`. Use `"remove"` to
        delete a list entry or clear a dict key. Before a `remove` or index-targeted `replace` on
        a list (e.g. `/characters/2`), prefix it with a `"test"` op asserting the value you expect
        to be there -- if the list has drifted since you last read it, the test fails with a
        clear, retryable error instead of silently mutating the wrong entry.

        The very first `update_story_bible` call of a session must include an op that sets
        `/mode` (e.g. `{"op": "add", "path": "/mode", "value": "from_scratch"}`) -- `mode` is
        fixed for the rest of the session from whatever that first call sets it to, and there is
        no way to change it afterward.

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
        if not isinstance(current, dict):
            current = {}

        pre_patch_mode = current.get("mode")
        pre_patch_length_tier = current.get("length_tier")
        is_bootstrap = "mode" not in current
        if is_bootstrap:
            if not any(op.path == "/mode" for op in patch):
                return (
                    "Rejected -- story_bible.json was NOT changed. The first update_story_bible "
                    'call of a session must set \'mode\' explicitly, e.g. {"op": "add", '
                    '"path": "/mode", "value": "from_scratch"}; it is fixed for the rest '
                    "of the session from whatever that first call sets it to."
                )
            current = _bootstrap_skeleton() | current

        try:
            patched = apply_patch(
                current,
                [op.model_dump(by_alias=True, exclude_unset=True) for op in patch],
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
        if pre_patch_length_tier is not None and bible.length_tier.value != pre_patch_length_tier:
            return (
                f"Rejected -- story_bible.json was NOT changed. 'length_tier' is fixed for this "
                f"session ({pre_patch_length_tier!r}) and cannot be changed by a patch."
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
