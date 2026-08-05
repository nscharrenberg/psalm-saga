from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psalm_saga.dimensions import GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.bible import make_update_story_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


def _op(op: str, path: str, value: Any = None, **kw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"op": op, "path": path}
    if value is not None:
        payload["value"] = value
    payload.update(kw)
    return payload


def test_creates_bible_from_scratch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    patch = [
        _op("replace", "/mode", "from_scratch"),
        _op("replace", "/premise", "A lighthouse keeper."),
    ]
    result = _invoke(tool, patch=patch)  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    on_disk = json.loads((tmp_path / "story_bible.json").read_text())
    assert on_disk["mode"] == "from_scratch"
    assert on_disk["premise"] == "A lighthouse keeper."


def test_replace_one_field_leaves_sibling_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/plot/structure", "three-act"),
        ],
    )
    _invoke(tool, patch=[_op("replace", "/plot/climax", "The light goes out for good.")])  # type: ignore[no-untyped-call]

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.plot.structure == "three-act"
    assert bible.plot.climax == "The light goes out for good."


def test_append_to_a_list_via_dash_path(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
        ],
    )
    _invoke(tool, patch=[_op("add", "/characters/-", {"name": "Odile", "role": "antagonist"})])  # type: ignore[no-untyped-call]

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert [c.name for c in bible.characters] == ["Mara", "Odile"]


def test_invalid_patch_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/premise", "A lighthouse keeper."),
        ],
    )
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(tool, patch=[_op("replace", "/mode", "not_a_real_mode")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_mode_cannot_be_changed_by_a_patch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/premise", "A lighthouse keeper."),
        ],
    )

    result = _invoke(tool, patch=[_op("replace", "/mode", "from_source")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert "cannot be changed" in result

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.mode is GenerationMode.FROM_SCRATCH


def test_recovers_from_corrupt_file_on_disk(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not valid json at all")
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/premise", "A fresh start."),
        ],
    )
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.premise == "A fresh start."


def test_stale_index_test_op_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
        ],
    )
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("test", "/characters/0/name", "SomeoneElse"),
            _op("remove", "/characters/0"),
        ],
    )
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_bad_path_is_rejected_and_file_untouched(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch=[_op("replace", "/mode", "from_scratch")])  # type: ignore[no-untyped-call]
    before = (tmp_path / "story_bible.json").read_text()

    result = _invoke(tool, patch=[_op("replace", "/nonexistent/field", "x")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert (tmp_path / "story_bible.json").read_text() == before


def test_first_call_bootstraps_a_full_skeleton_for_granular_second_call(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch=[_op("replace", "/mode", "from_scratch")])  # type: ignore[no-untyped-call]

    # Only possible if the first call's write already produced a full schema-shaped skeleton on
    # disk (every StoryBible field present with its default), not just the one key the first
    # patch explicitly touched.
    result = _invoke(tool, patch=[_op("replace", "/plot/structure", "three-act")])  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.plot.structure == "three-act"
