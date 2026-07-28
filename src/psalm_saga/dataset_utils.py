"""Pure, dependency-light helpers for dataset-item lifecycle decisions.

Deliberately kept in its own module, separate from `batch.py`: `batch.py` has heavy top-level
imports (`deepagents`, `langgraph`, `langchain_core`, transitively via `psalm_saga.agents`), so
merely importing it requires those packages installed. The decision logic here only needs
`pathlib`, so it can be imported and unit-tested on its own.
"""

from pathlib import Path
from typing import Literal

DatasetItemDecision = Literal["reuse_finished", "regenerate"]


def decide_dataset_item_action(session_dir: Path, *, overwrite: bool) -> DatasetItemDecision:
    """Decide whether a batch item's existing session directory (if any) can be reused.

    - No directory yet -> ``"regenerate"`` (nothing to reuse).
    - Directory exists, has a finished ``final_story.md``, and ``overwrite=False`` ->
      ``"reuse_finished"``.
    - Anything else -- ``overwrite=True``, or a directory *without* ``final_story.md`` (e.g. a
      leftover from a previous failed/partial attempt) -- -> ``"regenerate"``.

    The point of checking for ``final_story.md`` specifically, rather than just directory
    existence, is that a session directory is created (by `init_session`) *before* generation can
    fail -- so "directory exists" alone can't distinguish a finished item from a failed one. Get
    this wrong and a failed batch item gets silently reported as "skipped" (i.e. treated as done)
    on every subsequent retry instead of actually being regenerated.
    """
    if not session_dir.exists():
        return "regenerate"
    if (session_dir / "final_story.md").exists() and not overwrite:
        return "reuse_finished"
    return "regenerate"
