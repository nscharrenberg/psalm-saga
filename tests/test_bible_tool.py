from pathlib import Path

from psalm_saga.dimensions import Character, GenerationMode, StoryBible  # type: ignore[import-untyped]
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
    assert "not yet ready" in result
    assert "premise" in result


def test_validate_reports_ok_when_ready(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A clockmaker starts losing time itself, one hour at a time.",
        characters=[Character(name="Odile", role="protagonist")],
    )
    bible.plot.structure = "three-act"
    bible.plot.inciting_incident = "Odile's shop clock strikes an hour that hasn't happened yet."
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK: story_bible.json is schema-valid and has the minimum fields")


def test_validate_escalates_after_repeated_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json")
    tool = make_validate_bible_tool(tmp_path)

    first = _invoke(tool)  # type: ignore[no-untyped-call]
    second = _invoke(tool)  # type: ignore[no-untyped-call]
    third = _invoke(tool)  # type: ignore[no-untyped-call]

    assert "STOP" not in first
    assert "STOP" not in second
    assert "STOP" in third
    assert "update_story_bible" in third
    assert "story_bible_cleaned.json" in third


def test_validate_failure_counter_resets_after_success(tmp_path: Path) -> None:
    bible_path = tmp_path / "story_bible.json"
    tool = make_validate_bible_tool(tmp_path)

    bible_path.write_text("{not valid json")
    _invoke(tool)  # type: ignore[no-untyped-call]
    _invoke(tool)  # type: ignore[no-untyped-call]
    _invoke(tool)  # type: ignore[no-untyped-call] # 3 failures -> would have escalated on a 4th

    bible_path.write_text(StoryBible(mode=GenerationMode.FROM_SCRATCH).model_dump_json())
    ok_result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert ok_result.startswith("OK")

    bible_path.write_text("{not valid json")
    fresh_failure = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "STOP" not in fresh_failure  # counter reset, not still climbing from before
