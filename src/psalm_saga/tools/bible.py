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

from langchain_core.tools import tool
from pydantic import ValidationError

from psalm_saga.dimensions import StoryBible

BIBLE_FILENAME = "story_bible.json"


def make_validate_bible_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a ``validate_story_bible`` tool bound to one session's bible file.

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
        a precise list of schema errors to fix.
        """
        if not bible_path.exists():
            return f"{BIBLE_FILENAME} does not exist yet. Create it with write_file first."

        raw = bible_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"Invalid JSON in {BIBLE_FILENAME}: {exc}"

        try:
            bible = StoryBible.model_validate(data)
        except ValidationError as exc:
            return f"Schema errors in {BIBLE_FILENAME}:\n{exc}"

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
