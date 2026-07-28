"""Deterministic helpers for reading/validating ``story_bible.json``.

Agents write the bible using the built-in ``write_file``/``edit_file`` tools that
``FilesystemMiddleware`` already provides against our session's ``FilesystemBackend`` -- we don't
need to reinvent file I/O. What *is* worth adding is a cheap, non-LLM validation tool: JSON/schema
mistakes are exactly the kind of error a model can self-correct quickly if given a precise error
message, and catching them here is far cheaper than discovering them after the writer subagent
has already run.
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import ValidationError

from psalm_saga.dimensions import StoryBible

BIBLE_FILENAME = "story_bible.json"
_FAILURE_COUNTER_FILENAME = ".bible_validation_failures"
_ESCALATION_THRESHOLD = 3

def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` onto ``base``.

    Nested objects are merged key by key (so patching just ``plot.structure`` doesn't wipe out
    ``plot.climax``). Lists and scalars are replaced wholesale by whatever the patch provides --
    list fields (``characters``, ``scenes``, ``themes``, ``turning_points``,
    ``originality_findings``) have no sensible generic "merge" semantics, so callers pass the
    full list they want rather than a delta.
    """
    result = dict(base)
    for key, value in patch.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def make_update_story_bible_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build an ``update_story_bible`` tool bound to one session's bible file."""
    bible_path = session_dir / BIBLE_FILENAME

    @tool
    def update_story_bible(patch: dict[str, Any]) -> str:
        """Merge changes into story_bible.json and validate the result before writing it.

        ALWAYS use this to change story_bible.json -- never write_file or edit_file on it
        directly, and never create a different file for it (no story_bible_cleaned.json,
        story_bible_v2.json, etc.). This tool builds and validates the JSON itself, so the file
        on disk can never end up syntactically broken by going through it.

        Pass only the fields you're adding or changing, not the whole bible -- e.g.
        `{"premise": "...", "plot": {"inciting_incident": "..."}}` merges `inciting_incident`
        into the existing `plot` object without touching `plot.climax` or anything else already
        set. Nested objects are merged key by key like this; list fields (characters, scenes,
        themes, turning_points, originality_findings) are replaced wholesale by whatever you
        pass, so include the full list (existing entries plus your change), not just a delta.

        If the patch would produce an invalid bible, nothing is written -- you get back the
        specific validation error to fix in your next call.

        Args:
            patch: The fields to add or change, as a nested object matching the Story Bible
                schema (see psalm_dimensions_reference.md for what belongs in each dimension).
        """
        current: dict[str, Any] = {}
        recovering_from_corruption = False
        if bible_path.exists():
            try:
                current = json.loads(bible_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # The file on disk is already broken (e.g. from a prior write_file/edit_file
                # attempt before this tool existed, or a model bypassing it). There's no valid
                # prior state to merge onto, so treat this patch as authoring a fresh bible
                # instead of patching -- it must stand on its own.
                recovering_from_corruption = True

        merged = _deep_merge(current, patch) if not recovering_from_corruption else dict(patch)

        if "mode" in current and "mode" in patch and patch["mode"] != current["mode"]:
            return (
                f"Rejected -- story_bible.json was NOT changed. 'mode' is fixed for this "
                f"session ({current['mode']!r}) and cannot be changed by a patch."
            )

        try:
            bible = StoryBible.model_validate(merged)
        except ValidationError as exc:
            note = (
                " (story_bible.json on disk was corrupt; this patch needed to stand alone as a "
                "complete bible rather than a partial merge, since there was nothing valid to "
                "merge onto.)"
                if recovering_from_corruption
                else ""
            )
            return f"Patch rejected -- story_bible.json was NOT changed.{note}\n{exc}"

        bible_path.write_text(bible.model_dump_json(indent=2), encoding="utf-8")
        _reset_failure_counter(session_dir)

        ready, missing = bible.is_ready_for_writing()
        status = "ready for the writer subagent" if ready else f"missing: {', '.join(missing)}"
        recovered_note = " (recovered from a corrupt file on disk)" if recovering_from_corruption else ""
        return f"OK: story_bible.json updated{recovered_note} ({status})."

    return update_story_bible


def _failure_counter_path(session_dir: Path) -> Path:
    return session_dir / _FAILURE_COUNTER_FILENAME


def _bump_failure_counter(session_dir: Path) -> int:
    path = _failure_counter_path(session_dir)
    try:
        count = int(path.read_text(encoding="utf-8")) + 1
    except (FileNotFoundError, ValueError):
        count = 1
    path.write_text(str(count), encoding="utf-8")
    return count


def _reset_failure_counter(session_dir: Path) -> None:
    _failure_counter_path(session_dir).unlink(missing_ok=True)



def make_validate_bible_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a ``validate_story_bible`` tool bound to one session's bible file.

    This remains a safety net for the case where a subagent uses write_file/edit_file on
    story_bible.json directly despite being told to use update_story_bible instead -- it can
    detect that the file is broken, but (unlike update_story_bible) it can't fix it, since it
    doesn't control what gets written. After repeated consecutive failures, it escalates its
    message rather than repeating the same generic error forever, since a model stuck
    hand-patching raw JSON text tends to spiral (more failed edits, or new files like
    story_bible_cleaned.json) rather than converge.

    Args:
        session_dir: The session directory (also the root of the FilesystemBackend), so the
            tool reads the same file the agent's ``read_file``/``write_file`` tools operate on.
    """
    bible_path = session_dir / BIBLE_FILENAME

    @tool
    def validate_story_bible() -> str:
        """Validate story_bible.json against the PSALM-SAGA schema and report any errors.

        Call this after writing or editing story_bible.json, and again right before handing off
        to the writer subagent. Returns "OK" plus a summary of missing-but-recommended fields, or
        a precise list of schema errors to fix. Prefer update_story_bible over this + manual
        edits for actually fixing problems -- this tool only reports, it never repairs.
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
            failures = _bump_failure_counter(session_dir)
            message = f"Invalid JSON in {BIBLE_FILENAME}: {exc}"
            if failures >= _ESCALATION_THRESHOLD:
                message += (
                    f"\n\nThis is validation failure #{failures} in a row. STOP trying to "
                    "hand-edit the raw file with write_file/edit_file -- that is how it got "
                    "broken. Call update_story_bible instead, passing your full intended "
                    "content as its patch argument; it builds and validates the JSON itself, so "
                    "it cannot produce another syntax error. Do not create any other file "
                    "(no story_bible_cleaned.json, story_bible_fixed.json, etc.) -- "
                    "update_story_bible always targets story_bible.json itself."
                )
            return message

        try:
            bible = StoryBible.model_validate(data)
        except ValidationError as exc:
            _bump_failure_counter(session_dir)
            return (
                f"Schema errors in {BIBLE_FILENAME} (valid JSON, but doesn't match the Story "
                f"Bible schema):\n{exc}\n\nFix via update_story_bible with a patch for the "
                "offending field(s), not by hand-editing the file."
            )

        _reset_failure_counter(session_dir)
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
