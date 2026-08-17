"""Provides the `StreamRenderer` class for rendering live-updating Markdown segments
and tool-dispatch status lines within a console.

This module defines a framework for dynamically displaying segments of AI-generated
text in a live region, interspersed with static status messages signaling transitions
between tool interactions.

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
    between segments.

    A "segment" is the text of one AI message between tool calls — when a
    tool call happens, the current segment's Markdown is finalized into
    scrollback (`Live.stop()` leaves the last frame rendered) and a status
    line is printed before the next segment's live region starts.

    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._buffer = ""

    def _ensure_live(self) -> Live:
        if self._live is None:
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

    def finish(self) -> None:
        self._finalize_segment()
