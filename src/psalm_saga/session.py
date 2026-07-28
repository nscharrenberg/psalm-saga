"""On-disk session layout and lifecycle.

A "session" is one story-generation run: a directory containing the Story Bible, any source
text, the draft and final story, a LangGraph SQLite checkpoint database (so `ask_human`
interrupts survive across CLI invocations), and a small `session_config.json` recording what the
session was configured with, so `saga resume` doesn't need those flags repeated.

::

    <sessions_root>/<session_id>/
        session_config.json
        psalm_dimensions_reference.md   # copied in, read-only reference for the agents
        story_bible.json                # created empty by init_session, filled in by agents
        source.txt                      # only in from_source mode
        draft.md                        # written by writer-agent
        final_story.md                  # written by editor-agent
        checkpoints.sqlite               # LangGraph checkpointer storage
"""

import json
import shutil
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path

from psalm_saga.config import Settings
from psalm_saga.dimensions import GenerationMode, StoryBible, DivergencePlan
from psalm_saga.prompts import load_prompt

SESSION_CONFIG_FILENAME = "session_config.json"
DIMENSIONS_REFERENCE_FILENAME = "psalm_dimensions_reference.md"
SOURCE_FILENAME = "source.txt"


@dataclass(frozen=True, slots=True)
class SessionConfig:
    session_id: str
    mode: GenerationMode
    created_at: str
    model: str
    subagent_model: str
    originality_guard_strictness: str
    originality_guard_max_revisions: int
    initial_context: str = ""
    non_interactive: bool = False
    """True for batch/unattended sessions -- see `batch.py`. Threaded through to
        `build_orchestrator(..., non_interactive=...)` so `ask_human` never actually pauses."""


def new_session_id() -> str:
    """
    Generates a unique session identifier string consisting of the current timestamp
    and a truncated UUID.

    The session ID follows the format "YYYYMMDD-HHMMSS-XXXXXX", where:
    - "YYYYMMDD-HHMMSS" represents the current UTC timestamp.
    - "XXXXXX" is the first 6 characters of a generated UUID.

    :return: A string representing the unique session identifier.
    :rtype: str
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def session_dir_for(settings: Settings, session_id: str) -> Path:
    """
    Generates the directory path for a given session.

    This function constructs the directory path where session-specific data
    is stored by combining the root sessions directory from the settings
    object with the session identifier.

    :param settings: A `Settings` object containing configuration details,
                     including the root path for sessions.
    :param session_id: The unique identifier for the session.
    :return: The constructed `Path` object of the session directory.
    :rtype: Path
    """
    return settings.sessions_root / session_id


def init_session(
        settings: Settings,
        mode: GenerationMode,
        *,
        source_path: Path | None = None,
        initial_context: str = "",
        session_id: str | None = None,
        divergence_plan: DivergencePlan | None = None,
        non_interactive: bool = False,
) -> Path:
    """
    Initializes a new session for generation tasks and creates necessary session files
    and directories.

    This function sets up a unique session environment based on the provided settings
    and input parameters. It ensures that the session directory does not already exist
    to prevent overwriting previous sessions. Depending on the generation mode, it may
    also handle specific configurations such as loading a source file. The session is
    configured with details like session ID, generation mode, and initial context, which
    are saved for future use.

    :param settings: The configuration settings to be used for the session.
    :type settings: Settings
    :param mode: The mode of generation (e.g., from source or another mode).
    :type mode: GenerationMode
    :param source_path: The path to the source excerpt file, required when mode is
        GenerationMode.FROM_SOURCE. Defaults to None.
    :type source_path: Path | None
    :param initial_context: An optional initial context for the session. Defaults to an
        empty string.
    :type initial_context: str
    :param session_id: An optional identifier for the session. If not provided, a new
        session ID will be generated. Defaults to None.
    :type session_id: str | None
    :param non_interactive: True for batch/unattended sessions -- see `batch.py`. Threaded through to
        `build_orchestrator(..., non_interactive=...)` so `ask_human` never actually pauses.
    :type non_interactive: bool
    :return: The path to the directory where the session files are stored.
    :rtype: Path
    :raises FileExistsError: If the session directory already exists.
    :raises ValueError: If the mode is GenerationMode.FROM_SOURCE and source_path is not
        provided.
    """
    if divergence_plan is not None:
        if mode is not GenerationMode.FROM_SOURCE:
            raise ValueError("divergence_plan is only valid in from_source mode.")
        if not divergence_plan.is_complete():
            raise ValueError(
                "divergence_plan must cover every PSALM dimension; missing: "
                f"{divergence_plan.missing_dimensions()}"
            )

    session_id = session_id or new_session_id()
    session_dir = session_dir_for(settings, session_id)
    if session_dir.exists():
        raise FileExistsError(f"Session directory already exists: \"{session_dir}\".")

    session_dir.mkdir(parents=True, exist_ok=True)

    (session_dir / DIMENSIONS_REFERENCE_FILENAME).write_text(
        load_prompt("psalm_dimensions_reference"),
        encoding="utf-8",
    )

    bible = StoryBible(mode=mode)

    if mode is GenerationMode.FROM_SOURCE:
        if source_path is None:
            raise ValueError("from_source mode requires source_path.")

        dest = session_dir / SOURCE_FILENAME
        shutil.copyfile(source_path, dest)
        bible = StoryBible(
            mode=mode,
            source_excerpt_path=SOURCE_FILENAME,
            divergence_plan=divergence_plan
        )

    (session_dir / "story_bible.json").write_text(
        bible.model_dump_json(indent=2),
        encoding="utf-8",
    )

    config = SessionConfig(
        session_id=session_id,
        mode=mode,
        created_at=datetime.now(UTC).isoformat(),
        model=settings.model,
        subagent_model=settings.resolved_subagent_model(),
        originality_guard_strictness=settings.originality_guard_strictness.value,
        originality_guard_max_revisions=settings.originality_guard_max_revisions,
        initial_context=initial_context,
        non_interactive=non_interactive,
    )

    (session_dir / SESSION_CONFIG_FILENAME).write_text(
        json.dumps(asdict(config), indent=2, default=str),
        encoding="utf-8",
    )

    return session_dir


def load_session_config(session_dir: Path) -> SessionConfig:
    """
    Load the session configuration from a specified directory. The configuration file is expected to be in JSON
    format and located within the provided directory. The `mode` field in the configuration is converted to a
    `GenerationMode` enum instance before creating and returning a `SessionConfig` object.

    :param session_dir: The directory containing the session configuration file.
    :type session_dir: Path
    :return: A `SessionConfig` instance populated with the data from the configuration file.
    :rtype: SessionConfig
    """
    data = json.loads((session_dir / SESSION_CONFIG_FILENAME).read_text(encoding="utf-8"))
    data["mode"] = GenerationMode(data["mode"])

    return SessionConfig(**data)


def checkpoint_db_path(session_dir: Path) -> Path:
    """
    Generate the file path to the checkpoint database.

    This function constructs the full path to the "checkpoints.sqlite" database
    file within the specified session directory. It ensures consistency and
    reliability when referencing the checkpoint database location.

    :param session_dir: The path to the session directory where the database file
        is to be located.
    :type session_dir: Path
    :return: The complete path to the "checkpoints.sqlite" file in the specified
        session directory.
    :rtype: Path
    """
    return session_dir / "checkpoints.sqlite"
