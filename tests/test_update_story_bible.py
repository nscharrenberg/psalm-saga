from __future__ import annotations

import json
from pathlib import Path

from psalm_saga.dimensions import GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.bible import make_update_story_bible_tool, make_validate_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def test_creates_bible_from_scratch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    result = _invoke(tool, patch={"mode": "from_scratch", "premise": "A lighthouse keeper."})  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    on_disk = json.loads((tmp_path / "story_bible.json").read_text())
    assert on_disk["mode"] == "from_scratch"
    assert on_disk["premise"] == "A lighthouse keeper."


def test_patch_merges_nested_object_without_clobbering_siblings(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch={"mode": "from_scratch", "plot": {"structure": "three-act"}})  # type: ignore[no-untyped-call]
    _invoke(tool, patch={"plot": {"climax": "The light goes out for good."}})  # type: ignore[no-untyped-call]

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.plot.structure == "three-act"
    assert bible.plot.climax == "The light goes out for good."


def test_list_field_is_replaced_wholesale_not_merged(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch={
            "mode": "from_scratch",
            "characters": [{"name": "Mara", "role": "protagonist"}],
        },
    )
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch={
            "characters": [
                {"name": "Mara", "role": "protagonist"},
                {"name": "Odile", "role": "antagonist"},
            ]
        },
    )
    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert [c.name for c in bible.characters] == ["Mara", "Odile"]


def test_invalid_patch_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch={"mode": "from_scratch", "premise": "A lighthouse keeper."})  # type: ignore[no-untyped-call]
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(tool, patch={"mode": "not_a_real_mode"})  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_mode_cannot_be_changed_by_a_patch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch={"mode": "from_scratch", "premise": "A lighthouse keeper."})  # type: ignore[no-untyped-call]

    result = _invoke(tool, patch={"mode": "from_source"})  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert "cannot be changed" in result

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.mode is GenerationMode.FROM_SCRATCH


def test_recovers_from_corrupt_file_on_disk(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json at all")
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(tool, patch={"mode": "from_scratch", "premise": "A fresh start."})  # type: ignore[no-untyped-call]
    assert result.startswith("OK")
    assert "recovered" in result

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.premise == "A fresh start."


def test_successful_update_resets_the_validation_failure_counter(tmp_path: Path) -> None:
    validate = make_validate_bible_tool(tmp_path)
    update = make_update_story_bible_tool(tmp_path)

    (tmp_path / "story_bible.json").write_text("{not valid json")
    _invoke(validate)  # type: ignore[no-untyped-call]
    _invoke(validate)  # type: ignore[no-untyped-call]

    _invoke(update, patch={"mode": "from_scratch", "premise": "Recovered via the safe tool."})  # type: ignore[no-untyped-call]

    (tmp_path / "story_bible.json").write_text("{not valid json again")
    fresh_failure = _invoke(validate)  # type: ignore[no-untyped-call]
    assert "STOP" not in fresh_failure
