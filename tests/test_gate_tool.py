from pathlib import Path

from psalm_saga.config import GuardStrictness  # type: ignore[import-untyped]
from psalm_saga.dimensions import GenerationMode, OriginalityFinding, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.gate import (  # type: ignore[import-untyped,import-untyped]
    make_check_bible_readiness_tool,
    make_check_originality_gate_tool,
)


def _invoke(tool):  # type: ignore[no-untyped-def]
    return tool.invoke({})


def _write_bible(path: Path, bible: StoryBible) -> None:
    (path / "story_bible.json").write_text(bible.model_dump_json())


def test_proceeds_when_no_findings(tmp_path: Path) -> None:
    _write_bible(tmp_path, StoryBible(mode=GenerationMode.FROM_SCRATCH))
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.BLOCK)
    assert _invoke(tool).startswith("PROCEED")  # type: ignore[no-untyped-call]


def test_proceeds_when_all_findings_resolved(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        originality_findings=[
            OriginalityFinding(category="resemblance", description="fixed now", resolved=True)
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.BLOCK)
    assert _invoke(tool).startswith("PROCEED")  # type: ignore[no-untyped-call]


def test_warn_strictness_proceeds_with_open_findings(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        originality_findings=[
            OriginalityFinding(category="pastiche", description="too close to X", resolved=False)
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.WARN)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("PROCEED")
    assert "pastiche" in result


def test_block_strictness_blocks_with_open_findings(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        originality_findings=[
            OriginalityFinding(category="pastiche", description="too close to X", resolved=False)
        ],
    )
    _write_bible(tmp_path, bible)
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.BLOCK)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("BLOCKED")
    assert "pastiche" in result


def test_blocks_when_bible_missing(tmp_path: Path) -> None:
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.BLOCK)
    assert _invoke(tool).startswith("BLOCKED")  # type: ignore[no-untyped-call]


def test_blocks_when_bible_invalid(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not json")
    tool = make_check_originality_gate_tool(tmp_path, GuardStrictness.WARN)
    assert _invoke(tool).startswith("BLOCKED")  # type: ignore[no-untyped-call]


def test_check_bible_readiness_blocks_when_bible_missing(tmp_path: Path) -> None:
    tool = make_check_bible_readiness_tool(tmp_path)
    assert _invoke(tool).startswith("BLOCKED")  # type: ignore[no-untyped-call]


def test_check_bible_readiness_blocks_when_bible_invalid(tmp_path: Path) -> None:
    (tmp_path / "story_bible.json").write_text("{not json")
    tool = make_check_bible_readiness_tool(tmp_path)
    assert _invoke(tool).startswith("BLOCKED")  # type: ignore[no-untyped-call]


def test_check_bible_readiness_blocks_when_unsettled(tmp_path: Path) -> None:
    _write_bible(tmp_path, StoryBible(mode=GenerationMode.FROM_SCRATCH, premise="A lighthouse keeper."))
    tool = make_check_bible_readiness_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("BLOCKED")
    assert "writing_style" in result


def test_check_bible_readiness_proceeds_when_fully_settled(tmp_path: Path) -> None:
    from conftest import build_fully_settled_bible

    _write_bible(tmp_path, build_fully_settled_bible())
    tool = make_check_bible_readiness_tool(tmp_path)
    assert _invoke(tool).startswith("PROCEED")  # type: ignore[no-untyped-call]


def test_check_bible_readiness_proceeds_overridden_when_override_set(tmp_path: Path) -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A lighthouse keeper.",
        settlement_override=True,
        settlement_override_reason="user chose to proceed with the world-building unsettled",
    )
    _write_bible(tmp_path, bible)
    tool = make_check_bible_readiness_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("PROCEED (OVERRIDDEN)")
    assert "user chose to proceed with the world-building unsettled" in result
