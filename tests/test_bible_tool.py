from pathlib import Path

from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    Character,
    GenerationMode,
    StoryBible,
)
from psalm_saga.tools.bible import make_validate_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def test_validate_reports_missing_file(tmp_path: Path) -> None:
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "does not exist yet" in result


def test_validate_reports_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json")
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "Invalid JSON" in result


def test_validate_reports_schema_errors(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text('{"mode": "not_a_real_mode"}')
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "Schema errors" in result


def test_validate_reports_missing_required_fields(tmp_path: Path) -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "not yet fully settled" in result
    assert "premise" in result


def test_validate_reports_ok_when_ready(tmp_path: Path) -> None:
    from conftest import build_fully_settled_bible

    bible = build_fully_settled_bible()
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK: story_bible.json is schema-valid and fully settled")


def test_validate_does_not_escalate_after_repeated_invalid_json(tmp_path: Path) -> None:
    """Regression test for removing the failure-counter escalation ladder: repeated calls
    against the same broken file must stay flat (same plain message every time), not build up
    to a 'STOP hand-editing' message -- that mechanism targeted a corruption path that no longer
    exists now that update_story_bible is the only writer and validates before every write."""
    (tmp_path / "story_bible.json").write_text("{not valid json")
    tool = make_validate_bible_tool(tmp_path)

    for _ in range(5):
        result = _invoke(tool)  # type: ignore[no-untyped-call]
        assert "STOP" not in result
        assert "Invalid JSON" in result
