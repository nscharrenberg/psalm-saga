"""Rendering helpers for live session progress.

Turns two things deepagents already gives us for free -- the `todos` state channel from its
default `TodoListMiddleware` (the same mechanism Claude Code uses for its visible task list), and
every tool call/result that flows through the graph -- into human-readable lines. Kept separate
from `cli.py`'s actual Console/Prompt driving so the "how do I describe this tool call" logic is
reusable if a future UI wants a similarly-informative but differently-rendered feed (e.g. a web
UI would format these as structured events rather than Rich markup strings).

Nothing here should ever raise on unexpected input -- a rendering glitch on a tool call we didn't
anticipate must never take down a session, so callers should treat everything here as best-effort
and keep it wrapped in a broad try/except at the call site.
"""

from typing import Any

TodoItem = dict[str, str]

_STATUS_ICONS = {"completed": "☒", "in_progress": "◐", "pending": "☐"}

#: Small cosmetic map for our own known tools; anything else falls back to a plain arrow.
_TOOL_ICONS = {
    "think": "🤔",
    "ask_human": "❓",
    "task": "🧩",
    "write_file": "📝",
    "read_file": "📖",
    "edit_file": "✏️",
    "ls": "📂",
    "glob": "🔎",
    "grep": "🔎",
    "validate_story_bible": "✅",
    "check_originality_gate": "🚦",
    "check_fidelity_alignment": "🧮",
}

#: deepagents' `task` tool (subagent delegation) may name its subagent-identifying argument
#: differently across versions; try the plausible candidates rather than hard-coding one.
_SUBAGENT_ARG_KEYS = ("subagent_type", "subagent", "agent_name", "agent", "name")


def shorten(value: Any, limit: int = 90) -> str:
    """Collapse whitespace and truncate to a single readable log line."""
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_todos(todos: list[TodoItem]) -> str:
    """Render a todo list as Claude-Code-style checklist lines (Rich markup)."""
    lines: list[str] = []
    for item in todos:
        status = item.get("status", "pending")
        icon = _STATUS_ICONS.get(status, "☐")
        if status == "completed":
            lines.append(f"[green]{icon}[/green] [dim strike]{item.get('content', '')}[/dim strike]")
        elif status == "in_progress":
            label = item.get("active_form") or item.get("content", "")
            lines.append(f"[cyan]{icon}[/cyan] [bold cyan]{label}[/bold cyan]")
        else:
            lines.append(f"[dim]{icon}[/dim] {item.get('content', '')}")
    return "\n".join(lines)


def describe_tool_call(name: str, args: dict[str, Any]) -> str:
    """One-line, human-readable description of a tool call, for the activity log."""
    if name == "task":
        subagent = next((args[k] for k in _SUBAGENT_ARG_KEYS if args.get(k)), None)
        if subagent:
            desc = args.get("description") or args.get("task") or args.get("prompt") or ""
            suffix = f" -- {shorten(desc, 60)}" if desc else ""
            return f"🧩 delegating to [bold]{subagent}[/bold]{suffix}"
    if name == "think":
        return f"🤔 {shorten(args.get('thought', ''), 100)}"
    if name == "ask_human":
        return f"❓ asking: {shorten(args.get('question', ''), 90)}"
    icon = _TOOL_ICONS.get(name, "→")
    if args:
        preview = ", ".join(f"{k}={shorten(v, 40)}" for k, v in list(args.items())[:2])
        return f"{icon} {name}({preview})"
    return f"{icon} {name}()"


def describe_tool_result(name: str, content: Any) -> str:
    """One-line description of a tool's result, for the activity log."""
    icon = _TOOL_ICONS.get(name, "✓")
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return f"{icon} {shorten(content, 110)}"


def namespace_label(namespace: tuple[str, ...]) -> str:
    """Best-effort, human-readable prefix identifying which (sub)agent an update came from.

    LangGraph's exact namespace string format (from ``stream(..., subgraphs=True)``) isn't part
    of its stable public contract, so this deliberately degrades to an empty label -- rather than
    raising -- if the shape is ever different than expected: losing the "which subagent" prefix
    is a cosmetic regression, not a functional one.
    """
    if not namespace:
        return ""
    try:
        parts = [segment.split(":")[0] for segment in namespace]
        return f"[dim]\\[{'/'.join(parts)}][/dim] "
    except Exception:  # noqa: BLE001 - cosmetic only, must never break the run
        return ""
