"""Session identity and per-session storage layout for psalm-saga.

Every `psalm-saga` run works within one **session**: a UUIDv7 id that is
simultaneously the LangGraph `thread_id` and the name of a directory (under
`settings.backend.root_dir`) that holds that session's own SQLite
conversation-state database and its own copy of every spec/plan/chapter
file the skills write. Sessions never share a directory, so two stories
written in the same project directory never collide.

UUIDv7 (RFC 9562) rather than UUIDv4 specifically because its leading bits
encode a millisecond timestamp — the string form sorts lexicographically in
creation order, so `ls`, `sorted()`, and `--list-sessions` all show sessions
oldest-to-newest for free, with no separate timestamp needed in the name.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from psalm_saga.settings import Settings

SESSIONS_DIRNAME = "sessions"
CHECKPOINT_DB_FILENAME = "checkpoints.sqlite"


def _uuid7_fallback() -> uuid.UUID:
    """Hand-rolled RFC 9562 UUIDv7 for Python < 3.14.

    Python's stdlib `uuid` module only gained `uuid.uuid7()` in 3.14 (see
    https://docs.python.org/3/library/uuid.html — "Changed in version 3.14:
    Allow generating UUID versions 6, 7 and 8"). This project may run on
    earlier Python versions, so `generate_session_id()` uses the real
    stdlib function when available and falls back to this construction
    otherwise — same bit layout, same sortability, same validity, just
    built by hand: a 48-bit millisecond timestamp, the 4-bit version field
    set to 7, 10 bytes of CSPRNG randomness for the rest, and the 2-bit
    RFC 4122 variant field set.
    """
    unix_ts_ms = time.time_ns() // 1_000_000
    ts_bytes = unix_ts_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    raw = bytearray(ts_bytes + rand)
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # variant 10
    return uuid.UUID(bytes=bytes(raw))


def generate_session_id() -> str:
    """Return a fresh, string-sortable UUIDv7 session id."""
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return str(uuid7())
    return str(_uuid7_fallback())


def sessions_root(settings: Settings) -> Path:
    """The directory containing every session — `<root_dir>/sessions/`."""
    return settings.backend.root_dir / SESSIONS_DIRNAME


def session_directory(settings: Settings, session_id: str) -> Path:
    """The working directory for one specific session.

    This is what gets mounted as the project-files backend's `root_dir` —
    every spec/plan/chapter file a skill writes during this session lands
    here, not directly under `settings.backend.root_dir`.
    """
    return sessions_root(settings) / session_id


def checkpoint_db_path(settings: Settings, session_id: str) -> Path:
    """Path to this session's own SQLite conversation-state database."""
    return session_directory(settings, session_id) / CHECKPOINT_DB_FILENAME


@dataclass(frozen=True)
class SessionInfo:
    """Metadata about one existing session, for `--list-sessions`."""

    session_id: str
    directory: Path
    created_at: float
    """`directory`'s creation time (`st_ctime`), as a Unix timestamp."""


def list_sessions(settings: Settings) -> list[SessionInfo]:
    """List existing sessions under `settings.backend.root_dir`, oldest first.

    Returns an empty list if no sessions directory exists yet rather than
    raising — a fresh project with no sessions is a normal state, not an
    error.
    """
    root = sessions_root(settings)
    if not root.is_dir():
        return []
    infos = [
        SessionInfo(
            session_id=entry.name,
            directory=entry,
            created_at=entry.stat().st_ctime,
        )
        for entry in root.iterdir()
        if entry.is_dir()
    ]
    # UUIDv7 already sorts correctly by name, but sorting explicitly makes
    # the ordering guarantee independent of the id-generation scheme.
    infos.sort(key=lambda info: info.session_id)
    return infos
