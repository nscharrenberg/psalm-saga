"""Provides the `StreamRenderer` class for rendering live-updating Markdown segments
and tool-dispatch status lines within a console.

This module defines a framework for dynamically displaying segments of AI-generated
text in a live region, interspersed with static status messages signaling transitions
between tool interactions, and a spinner filling every gap where nothing is visibly
happening yet.

Classes:
    StreamRenderer: Handles live rendering of Markdown segments and static status
    updates during an AI-agent's interaction process.

"""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text


class StreamRenderer:
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
        self._status = self._console.status(f"[dim]{label}[/dim]", spinner="dots")
        self._status.start()

    def _ensure_live(self) -> Live:
        if self._live is None:
            self._stop_status()
            self._live = Live(Markdown(""), console=self._console, refresh_per_second=12)
            self._live.start()
        return self._live

    def add_token(self, content: str) -> None:
        if not content:
            return
        self._buffer += content
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
