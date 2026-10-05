# tests/experiments/test_progress.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.pipeline.progress import (
    JobProgress,
    stage_for_tool_call,
    tool_calls_from_update,
)


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("write_file", {"file_path": "drafts/story/story-spec.md"}, "spec"),
        ("write_file", {"file_path": "drafts/story/story-plan.md"}, "plan"),
        ("write_file", {"file_path": "drafts/story/chapter-2-title.md"}, "chapter 2"),
        ("write_file", {"file_path": "drafts/story/story-review.md"}, "review"),
        ("write_file", {"file_path": "drafts/story/ABANDONED.md"}, "abandoned"),
        ("edit_file", {"file_path": "drafts/story/chapter-1-title.md"}, "chapter 1"),
        ("task", {"subagent_type": "chapter-writer"}, "draft"),
        ("task", {"subagent_type": "dimension-reviewer"}, "review"),
        ("read_file", {"file_path": "anything.md"}, None),
    ],
)
def test_stage_for_tool_call(name: str, args: dict, expected: str | None) -> None:
    assert stage_for_tool_call(name, args) == expected


def test_tool_calls_are_extracted_from_an_updates_payload() -> None:
    message = SimpleNamespace(tool_calls=[{"name": "task", "args": {"subagent_type": "chapter-writer"}}])
    payload = {"model": {"messages": [message]}}
    assert tool_calls_from_update(payload) == [("task", {"subagent_type": "chapter-writer"})]


def test_job_progress_prints_and_appends_to_the_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "progress.log"
    progress = JobProgress(prefix="[1/2] story_a", log_path=log)
    progress.stage("spec")
    progress.stage("draft ch 2/5")
    assert "[1/2] story_a spec" in capsys.readouterr().out
    assert log.read_text(encoding="utf-8").splitlines() == [
        "[1/2] story_a spec",
        "[1/2] story_a draft ch 2/5",
    ]
