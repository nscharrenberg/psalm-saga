"""Progress reporting for generation jobs.

See the design spec §2. The backend reports stage changes through a
`ProgressSink`; the runner supplies a `JobProgress` that prints to the console
and appends to the job's `progress.log`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

_CHAPTER_RE = re.compile(r"chapter-(\d+)-")
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


class ProgressSink(Protocol):
    def stage(self, label: str) -> None: ...


class NullProgress:
    """A sink that ignores every stage. Used when no one is watching."""

    def stage(self, label: str) -> None:
        return None


class JobProgress:
    """Prints each stage line and appends it to the job's `progress.log`."""

    def __init__(self, prefix: str, log_path: Path) -> None:
        self._prefix = prefix
        self._log_path = log_path

    def stage(self, label: str) -> None:
        line = f"{self._prefix} {label}"
        print(line, flush=True)  # noqa: T201 — operator-facing progress output
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def stage_for_tool_call(name: str, args: dict[str, Any]) -> str | None:
    """Map one tool call to a human-readable stage, or None if it is not a stage change."""
    if name == "task":
        subagent = args.get("subagent_type")
        if subagent == "chapter-writer":
            return "draft"
        if subagent == "dimension-reviewer":
            return "review"
        return None
    if name in _WRITE_TOOLS:
        path = str(args.get("file_path", ""))
        if path.endswith("ABANDONED.md"):
            return "abandoned"
        if path.endswith("DONE.md"):
            return "done"
        if path.endswith("-spec.md"):
            return "spec"
        if path.endswith("-plan.md"):
            return "plan"
        if path.endswith("-review.md"):
            return "review"
        match = _CHAPTER_RE.search(path)
        if match:
            return f"chapter {match.group(1)}"
    return None


def tool_calls_from_update(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    """Extract `(name, args)` for every tool call in one `updates`-mode stream payload."""
    calls: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(payload, dict):
        return calls
    for node_update in payload.values():
        if not isinstance(node_update, dict):
            continue
        for message in node_update.get("messages", []) or []:
            for call in getattr(message, "tool_calls", None) or []:
                calls.append((call["name"], dict(call.get("args") or {})))
    return calls
