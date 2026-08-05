from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psalm_saga.dimensions import GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.bible import make_update_story_bible_tool  # type: ignore[import-untyped]


def _invoke(tool, **kwargs):  # type: ignore[no-untyped-def]
    return tool.invoke(kwargs)


_UNSET = object()


def _op(op: str, path: str, value: Any = _UNSET, **kw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"op": op, "path": path}
    if value is not _UNSET:
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


def test_length_tier_cannot_be_changed_by_a_patch(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op("replace", "/length_tier", "medium"),
            _op("replace", "/premise", "A lighthouse keeper."),
        ],
    )

    result = _invoke(tool, patch=[_op("replace", "/length_tier", "short")])  # type: ignore[no-untyped-call]
    assert "rejected" in result.lower()
    assert "cannot be changed" in result

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.length_tier.value == "medium"


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


def test_first_call_omitting_mode_is_rejected_and_nothing_written(tmp_path: Path) -> None:
    """Regression test for the critical bootstrap bug: a first patch with no /mode op used to be
    silently accepted with the placeholder "from_scratch" mode committed to disk, permanently
    locking the session into it. It must now be rejected outright, before the placeholder mode
    (or anything else) ever gets written.
    """
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("replace", "/premise", "A lighthouse keeper.")],
    )
    assert "rejected" in result.lower()
    assert not (tmp_path / "story_bible.json").exists()


def test_first_call_with_mode_still_works_and_second_call_can_be_granular(tmp_path: Path) -> None:
    """Companion to the omitted-mode rejection test above: a first call that DOES set /mode
    (whether via "add" or "replace") must keep working exactly as before, and later calls must
    still be able to use granular ops without re-specifying mode.
    """
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("add", "/mode", "from_source"), _op("replace", "/premise", "A radio signal.")],
    )
    assert result.startswith("OK")

    result = _invoke(tool, patch=[_op("replace", "/plot/structure", "three-act")])  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.mode is GenerationMode.FROM_SOURCE
    assert bible.premise == "A radio signal."
    assert bible.plot.structure == "three-act"


def test_divergence_plan_must_be_added_whole_not_descended_into(tmp_path: Path) -> None:
    """Regression test for the brainstorm.md guidance bug: divergence_plan is None until first
    set, so a patch targeting a path underneath it (e.g. /divergence_plan/per_dimension/plot)
    cannot descend into it and is rejected 100% of the time. The corrected pattern -- one "add" op
    that materializes the whole divergence_plan object at once -- must succeed.
    """
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(tool, patch=[_op("add", "/mode", "from_source")])  # type: ignore[no-untyped-call]

    # The old (broken) guidance: targeting a key inside the still-null divergence_plan directly.
    broken = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[_op("replace", "/divergence_plan/per_dimension/plot", "moderate")],
    )
    assert "rejected" in broken.lower()

    # The corrected guidance: materialize the whole container in one op.
    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op(
                "add",
                "/divergence_plan",
                {
                    "per_dimension": {
                        "writing_style": "close",
                        "narrative_voice": "close",
                        "characters": "moderate",
                        "plot": "loose",
                        "scenes": "loose",
                        "world_building": "divergent",
                    }
                },
            )
        ],
    )
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.divergence_plan is not None
    assert bible.divergence_plan.per_dimension["plot"] == "loose"
    assert bible.divergence_plan.is_complete()


def test_explicit_null_value_is_preserved_and_can_clear_a_nullable_field(tmp_path: Path) -> None:
    """Regression test for the exclude_none bug: JsonPatchOperation.value defaults to None, so
    exclude_none couldn't distinguish "no value supplied" from "value is explicitly null" and any
    patch trying to set a nullable field back to null was rejected as missing `value`.
    """
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("add", "/mode", "from_scratch"),
            _op("replace", "/target_length_words", 5000),
        ],
    )
    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.target_length_words == 5000

    result = _invoke(tool, patch=[_op("replace", "/target_length_words", None)])  # type: ignore[no-untyped-call]
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.target_length_words is None


def test_non_object_json_on_disk_falls_back_like_a_parse_failure(tmp_path: Path) -> None:
    """Regression test: valid JSON that isn't an object (e.g. a bare list) used to crash with an
    uncaught AttributeError on current.get("mode") instead of falling back the same way corrupt/
    unparseable JSON does.
    """
    (tmp_path / "story_bible.json").write_text("[]")
    tool = make_update_story_bible_tool(tmp_path)

    result = _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("add", "/mode", "from_scratch"),
            _op("replace", "/premise", "A fresh start."),
        ],
    )
    assert result.startswith("OK")

    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.premise == "A fresh start."


def test_append_chapter_via_dash_path(tmp_path: Path) -> None:
    tool = make_update_story_bible_tool(tmp_path)
    _invoke(  # type: ignore[no-untyped-call]
        tool,
        patch=[
            _op("replace", "/mode", "from_scratch"),
            _op(
                "add",
                "/chapters/-",
                {"index": 1, "title": "The First Letter", "target_word_count": 2000},
            ),
        ],
    )
    bible = StoryBible.model_validate_json((tmp_path / "story_bible.json").read_text())
    assert bible.chapters[0].title == "The First Letter"
    assert bible.chapters[0].status == "planned"
