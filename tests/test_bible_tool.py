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
