from __future__ import annotations

from pathlib import Path

from psalm_saga.dataset_utils import decide_dataset_item_action


def test_regenerate_when_no_directory_exists(tmp_path: Path) -> None:
    session_dir = tmp_path / "does-not-exist"
    assert decide_dataset_item_action(session_dir, overwrite=False) == "regenerate"


def test_reuse_finished_when_final_story_exists(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "final_story.md").write_text("The end.")
    assert decide_dataset_item_action(session_dir, overwrite=False) == "reuse_finished"


def test_regenerate_when_overwrite_requested_even_if_finished(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "final_story.md").write_text("The end.")
    assert decide_dataset_item_action(session_dir, overwrite=True) == "regenerate"


def test_regenerate_when_directory_exists_but_never_finished(tmp_path: Path) -> None:
    """Regression test: a directory left over from a failed/partial attempt (no final_story.md)
    must be retried, not silently reported as already done -- init_session creates the directory
    *before* generation can fail, so "directory exists" alone can't mean "this item succeeded"."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "story_bible.json").write_text("{}")  # partial artifacts, but no final_story.md
    assert decide_dataset_item_action(session_dir, overwrite=False) == "regenerate"
