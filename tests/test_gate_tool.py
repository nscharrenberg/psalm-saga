from pathlib import Path

from psalm_saga.config import GuardStrictness  # type: ignore[import-untyped]
from psalm_saga.dimensions import GenerationMode, OriginalityFinding, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.gate import make_check_originality_gate_tool  # type: ignore[import-untyped,import-untyped]


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
