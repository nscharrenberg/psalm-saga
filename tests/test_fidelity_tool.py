from pathlib import Path

from psalm_saga.dimensions import DivergenceIntensity, DivergencePlan, GenerationMode, StoryBible  # type: ignore[import-untyped]
from psalm_saga.tools.fidelity import make_check_fidelity_tool  # type: ignore[import-untyped]

def _invoke(tool):  # type: ignore[no-untyped-def]
    return tool.invoke({})


def _write_bible(path: Path, bible: StoryBible) -> None:
    (path / "story_bible.json").write_text(bible.model_dump_json())


def test_no_divergence_plan(tmp_path: Path) -> None:
    _write_bible(tmp_path, StoryBible(mode=GenerationMode.FROM_SOURCE))
    tool = make_check_fidelity_tool(tmp_path)
    assert "No divergence_plan" in _invoke(tool)  # type: ignore[no-untyped-call]


def test_missing_achieved_divergence(tmp_path: Path) -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SOURCE, divergence_plan=DivergencePlan.isolate("plot"))
    _write_bible(tmp_path, bible)
    tool = make_check_fidelity_tool(tmp_path)
    assert "achieved_divergence is empty" in _invoke(tool)  # type: ignore[no-untyped-call]


def test_reports_ok_when_aligned(tmp_path: Path) -> None:
    plan = DivergencePlan.isolate("plot")
    bible = StoryBible(
        mode=GenerationMode.FROM_SOURCE,
        divergence_plan=plan,
        achieved_divergence=dict(plan.per_dimension),
    )
    _write_bible(tmp_path, bible)
    tool = make_check_fidelity_tool(tmp_path)
    assert _invoke(tool).startswith("OK")  # type: ignore[no-untyped-call]


def test_reports_mismatches(tmp_path: Path) -> None:
    plan = DivergencePlan.isolate("plot")
    achieved = dict(plan.per_dimension)
    achieved["characters"] = DivergenceIntensity.CLOSE  # was DIVERGENT in the plan
    bible = StoryBible(mode=GenerationMode.FROM_SOURCE, divergence_plan=plan, achieved_divergence=achieved)
    _write_bible(tmp_path, bible)
    tool = make_check_fidelity_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert "Fidelity mismatches found" in result
    assert "characters" in result
