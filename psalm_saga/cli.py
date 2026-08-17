"""Interactive CLI for psalm-saga.

Run `psalm-saga` in a project directory to start a session. Every session
gets its own directory under `settings.backend.root_dir` (see
`psalm_saga.session`) holding its own SQLite conversation-state database
and its own copy of every spec/plan/chapter file the skills write,
following the story-brainstorming → writing-story-plans → drafting-chapters
→ reviewing-story-dimensions workflow the `using-psalm-saga` skill enforces.

Output is rendered with `rich` (the agent's responses are Markdown —
dimension specs, coverage checklists, prose — and deserve to render as
such, not as flat text) and input is handled by `prompt_toolkit` — real
multi-line editing (Enter submits, Ctrl+J or Alt+Enter adds a line without
submitting) and persistent history, since brainstorming answers and chapter
feedback tend to be long and benefit from actual structure.
"""

import argparse
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from psalm_saga.agent import build_agent, open_sqlite_checkpointer
from psalm_saga.session import generate_session_id, list_sessions, session_directory
from psalm_saga.settings import Settings

_BANNER = r"""[bold cyan]
 _ __  ___  __ _| |_ __ ___    ___  __ _  __ _  __ _
| '_ \/ __|/ _` | | '_ ` _ \  / __|/ _` |/ _` |/ _` |
| |_) \__ \ (_| | | | | | | | \__ \ (_| | (_| | (_| |
| .__/|___/\__,_|_|_| |_| |_| |___/\__,_|\__, |\__,_|
|_|                                      |___/[/bold cyan]
[dim]A spec-first, PSALM-dimension-aligned story-writing agent.[/dim]"""

_HELP = """\
### Commands

- `/help`    — show this message
- `/reset`   — start a brand new session (fresh directory, fresh history)
- `/session` — show the current session id and its directory
- `/exit`, `/quit` — end the session (Ctrl+D / Ctrl+C also work)

### Multi-line input

`Enter` sends your message. `Ctrl+J` (or `Alt+Enter`) inserts a new line
without sending — use it for lists, multi-paragraph answers, or Markdown:

    ### Point 1
    explanation of point 1

    ### Point 2
    explanation of point 2

Anything else is sent to the agent. On first message in a fresh session,
expect it to open with the `story-brainstorming` skill rather than writing
prose immediately — that's the spec-first workflow working as intended.\
"""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="psalm-saga",
        description="A spec-first, PSALM-dimension-aligned story-writing agent.",
    )
    parser.add_argument(
        "--session",
        dest="session_id",
        default=None,
        help="Resume a specific session id instead of starting a fresh one. "
        "If a session with this id already exists, its full conversation "
        "history is loaded and replayed before the prompt. See "
        "--list-sessions for existing ids.",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List existing sessions (oldest first) and exit without starting one.",
    )
    parser.add_argument(
        "--model",
        dest="model",
        default=None,
        help="Override the main-loop model (e.g. anthropic:claude-sonnet-4-6, "
        "openai:gpt-4o). Overrides PSALM_SAGA_AGENT__ORCHESTRATION_MODEL_NAME.",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Skip the startup banner (useful when piping output).",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Don't persist input history to disk for this session.",
    )
    return parser.parse_args(argv)


def _build_key_bindings() -> KeyBindings:
    """Enter submits; Ctrl+J or Alt+Enter inserts a newline instead.

    `PromptSession(multiline=True)` on its own binds Enter to *insert a
    newline* and requires Alt+Enter to submit — the opposite of what a chat
    prompt wants. These bindings flip that: Enter always submits, and both
    Ctrl+J (the portable choice — most terminals don't reliably distinguish
    Ctrl+Enter from plain Enter at the protocol level, unlike Ctrl+J which
    is the literal linefeed byte) and Alt+Enter (reliably distinguishable in
    virtually every terminal) insert a line instead.
    """
    bindings = KeyBindings()

    @bindings.add("c-j")
    def _insert_newline_ctrl_j(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("escape", "enter")
    def _insert_newline_alt_enter(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("enter")
    def _submit(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    return bindings


def _build_prompt_session(settings: Settings, persist_history: bool) -> PromptSession:  # noqa: FBT001
    """Build the input session: multi-line editing, and on-disk history
    unless disabled.

    History lives under `<root_dir>/.psalm-saga/history` — shared across
    every session in this project directory (not per-session), since the
    point of input history is recalling things you typed before regardless
    of which session you typed them in.
    """
    history: History
    if persist_history:
        history_dir = settings.backend.root_dir / ".psalm-saga"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_dir / "history"))
    else:
        history = InMemoryHistory()
    return PromptSession(multiline=True, key_bindings=_build_key_bindings(), history=history)


def _extract_text(content: Any) -> str:
    """Normalize a streamed `AIMessageChunk.content` into plain text.

    `content` is a plain `str` for most providers/models. For OpenAI's
    Responses API — needed for GPT-5-reasoning-family models, since they
    reject `reasoning_effort` together with function tools on the Chat
    Completions API (see `Settings.agent.model_kwargs`) — it's instead a
    list of typed content blocks, e.g. `{"type": "text", "text": "..."}` or
    `{"type": "reasoning", "summary": [...]}`. Only `text` blocks are
    rendered as story prose; `reasoning` blocks are the model's internal
    thinking, not output meant for the reader, and are intentionally
    skipped rather than interleaved into the rendered story. Unrecognized
    shapes fall back to an empty string rather than raising, since this
    runs on every streamed token and a malformed chunk shouldn't crash the
    session.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        # other block types (reasoning, tool_use, etc.) are intentionally skipped
    return "".join(parts)


class _StreamRenderer:
    """Renders a streamed agent turn: Markdown segments in a live-updating
    region, with tool-dispatch status lines printed as static scrollback
    between segments, and a spinner filling every gap where nothing is
    visibly happening yet.

    A "segment" is the text of one AI message between tool calls — when a
    tool call happens, the current segment's Markdown is finalized into
    scrollback (`Live.stop()` leaves the last frame rendered) and a status
    line is printed before the next segment's live region starts.

    Without the spinner, there is a real, often multi-second silence (e.g.
    while a dispatched subagent runs, or before the first token of a
    response arrives) with no indication anything is happening — the cursor
    just blinks. The spinner runs by default and is only suspended while a
    `Live` text region is actively rendering.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._buffer = ""
        self._status = console.status("[dim]saga is thinking…[/dim]", spinner="dots")
        self._status.start()

    def _stop_status(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None

    def _start_status(self, label: str = "saga is thinking…") -> None:
        # Rich's Console keeps a *stack* of active Live/Status regions —
        # starting a new one without stopping the previous first pushes it
        # onto that stack instead of replacing it, and the earlier one
        # becomes permanently unreachable and leaks indefinitely. Always
        # stop first so at most one status is ever active.
        self._stop_status()
        self._status = self._console.status(f"[dim]{label}[/dim]", spinner="dots")
        self._status.start()

    def _ensure_live(self) -> Live:
        if self._live is None:
            self._stop_status()
            self._live = Live(Markdown(""), console=self._console, refresh_per_second=12)
            self._live.start()
        return self._live

    def add_token(self, content: Any) -> None:
        text = _extract_text(content)
        if not text:
            return
        self._buffer += text
        self._ensure_live().update(Markdown(self._buffer))

    def _finalize_segment(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._buffer = ""

    def announce_tool_call(self, message: str) -> None:
        self._finalize_segment()
        self._console.print(Text(f"  → {message}", style="dim cyan"))
        # A dispatched subagent (or any tool call) can take a while — keep
        # the spinner running for this gap too, not just the first one.
        self._start_status(f"waiting on {message}…")

    def finish(self) -> None:
        self._finalize_segment()
        self._stop_status()


def _extract_tool_call_lines(update: dict[str, Any]) -> list[str]:
    """Best-effort extraction of tool-call announcements from a LangGraph
    `updates`-mode payload for the main agent's `model` node.

    This is a convenience for terminal feedback, not load-bearing — if the
    update shape doesn't match what's expected (e.g. a deepagents internal
    change), it returns nothing rather than raising.
    """
    lines: list[str] = []
    try:
        model_output = update.get("model")
        if not model_output:
            return lines
        for message in model_output.get("messages", []):
            for tool_call in getattr(message, "tool_calls", None) or []:
                name = tool_call.get("name", "tool")
                if name == "task":
                    subagent = tool_call.get("args", {}).get("subagent_type", "?")
                    lines.append(f"dispatching {subagent}")
                else:
                    lines.append(name)
    except Exception:  # noqa: BLE001 — status lines are best-effort only
        return lines
    return lines


def _replay_history(agent: Any, config: dict[str, Any], console: Console) -> None:
    """Print a resumed session's prior conversation before the prompt starts.

    Only `HumanMessage` and text-bearing `AIMessage` turns are shown —
    `ToolMessage`s and tool-call-only `AIMessage`s (e.g. the `write_todos`
    calls during brainstorming) are replay noise, not conversation content,
    and are skipped the same way live tool-call announcements aren't part
    of the rendered story text either.
    """
    state = agent.get_state(config)
    messages = state.values.get("messages", []) if state.values else []
    if not messages:
        return

    console.print(Panel(f"[dim]Resuming — {len(messages)} prior messages[/dim]", expand=False))
    for message in messages:
        text = _extract_text(getattr(message, "content", ""))
        if not text.strip():
            continue
        if message.type == "human":
            console.print(f"[bold green]you>[/bold green] {text}")
        elif message.type == "ai":
            console.print("[bold magenta]saga>[/bold magenta]")
            console.print(Markdown(text))
    console.print()


def _print_session_list(settings: Settings, console: Console) -> None:
    infos = list_sessions(settings)
    if not infos:
        console.print("[dim]No sessions yet.[/dim]")
        return
    for info in infos:
        created = datetime.fromtimestamp(info.created_at, tz=UTC)
        console.print(f"[bold]{info.session_id}[/bold]  [dim]{created:%Y-%m-%d %H:%M:%S} UTC[/dim]")


def run_session(
    agent: Any, session_id: str, console: Console, session: PromptSession
) -> str | None:
    """Run the interactive read-eval-print loop for one session.

    Returns `"reset"` if the user asked to start a new session (the caller
    is responsible for tearing down this session's checkpointer/backend and
    building a fresh one — a running session is bound to one specific
    session-scoped backend and SQLite connection, so `/reset` can't just
    swap a config value the way it could when state was purely in-memory),
    or `"exit"` if the session ended normally.
    """
    config = {"configurable": {"thread_id": session_id}}

    console.print(f"[dim]Session:[/dim] {session_id}")
    console.print("[dim]Type /help for commands. Ctrl+D or /exit to leave.[/dim]\n")

    while True:
        try:
            user_input = session.prompt(HTML("<b fg='green'>you</b>> ")).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return "exit"

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            return "exit"
        if user_input == "/help":
            console.print(Markdown(_HELP))
            continue
        if user_input == "/session":
            console.print(f"[dim]Session:[/dim] {session_id}")
            continue
        if user_input == "/reset":
            return "reset"

        console.print("[bold magenta]saga>[/bold magenta]")
        renderer = _StreamRenderer(console)
        try:
            for mode, payload in agent.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode=["messages", "updates"],
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "model":
                        renderer.add_token(getattr(chunk, "content", ""))
                elif mode == "updates":
                    for line in _extract_tool_call_lines(payload):
                        renderer.announce_tool_call(line)
        except KeyboardInterrupt:
            renderer.finish()
            console.print("\n[yellow][interrupted][/yellow]")
            continue
        renderer.finish()
        console.print()


def _run_one_session(
    settings: Settings, session_id: str, console: Console, prompt_session: PromptSession
) -> str:
    """Open this session's checkpointer, build its agent, replay history if
    resuming, and run the interactive loop — all within one `with` block so
    the SQLite connection is always closed on the way out, however the loop
    ends (normal exit, `/reset`, or an exception).
    """
    is_resuming = session_directory(settings, session_id).exists()

    with open_sqlite_checkpointer(settings, session_id) as checkpointer:
        agent = build_agent(settings, session_id=session_id, checkpointer=checkpointer)

        console.print(f"[dim]Session directory:[/dim] {session_directory(settings, session_id)}\n")

        if is_resuming:
            _replay_history(agent, {"configurable": {"thread_id": session_id}}, console)

        return run_session(agent, session_id, console, prompt_session)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `psalm-saga` console script."""
    load_dotenv()
    args = _parse_args(argv)
    console = Console()

    settings = Settings()
    if args.model:
        settings.agent.orchestration_model_name = args.model

    if args.list_sessions:
        _print_session_list(settings, console)
        return

    if not args.no_banner:
        console.print(Panel(_BANNER, expand=False, border_style="cyan"))
    console.print(f"[dim]Project directory:[/dim] {settings.backend.root_dir}")
    console.print(f"[dim]Model:[/dim] {settings.agent.orchestration_model_name}\n")

    prompt_session = _build_prompt_session(settings, persist_history=not args.no_history)
    session_id = args.session_id or generate_session_id()

    while True:
        outcome = _run_one_session(settings, session_id, console, prompt_session)
        if outcome == "exit":
            return
        # outcome == "reset": start a brand new session and loop.
        session_id = generate_session_id()
        console.print(f"[dim]Started a new session:[/dim] {session_id}\n")


if __name__ == "__main__":
    main()
