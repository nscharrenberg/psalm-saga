"""Interactive CLI for psalm-saga.

Run `psalm-saga` in a project directory to start a session. The agent reads
and writes spec/plan/chapter files relative to that directory (see
`settings.BackendSettings.root_dir`), following the story-brainstorming →
writing-story-plans → drafting-chapters → reviewing-story-dimensions
workflow the `using-psalm-saga` skill enforces.

Output is rendered with `rich` (the agent's responses are Markdown —
dimension specs, coverage checklists, prose — and deserve to render as
such, not as flat text) and input is handled by `prompt_toolkit` (history
and proper line editing matter more here than in a typical one-line CLI
prompt, since brainstorming answers and chapter feedback tend to be long).
"""

import argparse
import uuid
from typing import Any

from dotenv import load_dotenv
from prompt_toolkit import HTML, PromptSession
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from psalm_saga.agent import build_agent
from psalm_saga.settings import Settings
from psalm_saga.stream_renderer import StreamRenderer

_BANNER = r"""[bold cyan]
▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄   ▄▄▄▄   ▄▄▄      ▄▄▄      ▄▄▄    ▄▄▄▄▄▄▄   ▄▄▄▄    ▄▄▄▄▄▄▄    ▄▄▄▄
███▀▀███▄ █████▀▀▀ ▄██▀▀██▄ ███      ████▄  ▄████   █████▀▀▀ ▄██▀▀██▄ ███▀▀▀▀▀  ▄██▀▀██▄
███▄▄███▀  ▀████▄  ███  ███ ███      ███▀████▀███    ▀████▄  ███  ███ ███       ███  ███
███▀▀▀▀      ▀████ ███▀▀███ ███      ███  ▀▀  ███      ▀████ ███▀▀███ ███  ███▀ ███▀▀███
███       ███████▀ ███  ███ ████████ ███      ███   ███████▀ ███  ███ ▀██████▀  ███  ███
                                    |___/[/bold cyan]
[dim]A spec-first, PSALM-dimension-aligned story-writing agent.[/dim]"""

_HELP = """\
### Commands

- `/help`   — show this message
- `/reset`  — start a new story thread (keeps the same project files)
- `/thread` — show the current thread id
- `/exit`, `/quit` — end the session (Ctrl+D / Ctrl+C also work)

Anything else is sent to the agent. On first message in a fresh project,
expect it to open with the `story-brainstorming` skill rather than writing
prose immediately — that's the spec-first workflow working as intended.\
"""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="psalm-saga",
        description="A spec-first, PSALM-dimension-aligned story-writing agent.",
    )

    parser.add_argument(
        "--thread",
        dest="thread_id",
        default=None,
        help="Resume a specific thread id instead of starting a fresh one "
        "(only meaningful with a persistent checkpointer; the default "
        "in-memory one doesn't survive past this process).",
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


def _build_prompt_session(settings: Settings, persist_history: bool) -> PromptSession:  # noqa: FBT001 boolean indication is clear enough
    """Build the input session, with on-disk history unless disabled.

    History lives under `<root_dir>/.psalm-saga/history` — alongside the
    project it belongs to, the same way the spec/plan/chapter files
    `story-brainstorming` and friends write are project-relative rather than
    global.

    Args:
        settings: Application settings used to determine the root directory for storing
            history files if persistence is enabled.
        persist_history: A flag indicating whether the session history should be
            persisted to a file (True) or stored in memory (False).

    Returns:
        PromptSession: A configured instance of PromptSession with the specified
        history backend.

    """
    history: History

    if persist_history:
        history_dir = settings.backend.root_dir / ".psalm-saga"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_dir / "history"))
    else:
        history = InMemoryHistory()

    return PromptSession(history=history)


def _extract_tool_call_lines(update: dict[str, Any]) -> list[str]:
    """Best-effort extraction of tool-call announcements from a LangGraph
    `updates`-mode payload for the main agent's `model` node.

    This is a convenience for terminal feedback, not load-bearing — if the
    update shape doesn't match what's expected (e.g. a deepagents internal
    change), it returns nothing rather than raising.

    Args:
        update (dict[str, Any]): A dictionary containing the model's output and
            associated data. The dictionary is expected to have a `model` key
            with details about tool calls in its "messages" attribute.

    Returns:
        list[str]: A list of formatted strings representing tool call lines.
        If no tool calls are found or an error occurs, the list will be empty.

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
    except Exception:  # noqa: BLE001 status lines are best-effort only
        return lines

    return lines


def run_session(agent: Any, thread_id: str, console: Console, session: PromptSession) -> None:
    """Run the interactive read-eval-print loop for one session."""
    config = {"configurable": {"thread_id": thread_id}}

    console.print(f"[dim]Thread:[/dim] {thread_id}")
    console.print("[dim]Type /help for commands. Ctrl+D or /exit to leave.[/dim]\n")

    while True:
        try:
            user_input = session.prompt(HTML("<b fg='green'>you</b>> ")).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            console.print("[dim]Goodbye.[/dim]")
            return

        if user_input == "/help":
            console.print(Markdown(_HELP))
            continue

        if user_input == "/thread":
            console.print(f"[dim]Thread:[/dim] {thread_id}")
            continue

        if user_input == "/reset":
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            console.print(f"[dim]Started a new thread:[/dim] {thread_id}")
            continue

        console.print("[bold magenta]saga>[/bold magenta] ", end="")
        renderer = StreamRenderer(console)

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


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `psalm-saga` console script."""
    load_dotenv()

    args = _parse_args(argv)
    console = Console()

    settings = Settings()
    if args.model:
        settings.agent.orchestration_model_name = args.model

    if not args.no_banner:
        console.print(Panel(_BANNER, expand=False, border_style="cyan"))

    console.print(f"[dim]Project directory:[/dim] {settings.backend.root_dir}")
    console.print(f"[dim]Model:[/dim] {settings.agent.orchestration_model_name}\n")

    agent = build_agent(settings)

    thread_id = args.thread_id or str(uuid.uuid4())
    session = _build_prompt_session(settings, persist_history=not args.no_history)

    run_session(agent, thread_id, console, session)


if __name__ == "__main__":
    main()
