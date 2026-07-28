import json

import pytest
from pydantic import ValidationError

from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    Character,
    DivergencePlan,
    GenerationMode,
    OriginalityFinding,
    StoryBible, DivergenceIntensity, evaluate_fidelity, PSALM_DIMENSIONS,
)


def test_empty_bible_round_trips_through_json() -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    payload = bible.model_dump_json()
    restored = StoryBible.model_validate(json.loads(payload))
    assert restored == bible


def test_is_ready_for_writing_reports_missing_fields() -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    ready, missing = bible.is_ready_for_writing()
    assert ready is False
    assert "premise" in missing
    assert "characters" in missing
    assert "plot.structure" in missing
    assert "plot.inciting_incident" in missing


def test_is_ready_for_writing_true_once_minimum_fields_set() -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A lighthouse keeper discovers the sea remembers everything it swallows.",
        characters=[Character(name="Mara", role="protagonist")],
    )
    bible.plot.structure = "three-act"
    bible.plot.inciting_incident = "A drowned bell washes ashore, still ringing."
    ready, missing = bible.is_ready_for_writing()
    assert ready is True
    assert missing == []


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        StoryBible.model_validate({"mode": "from_scratch", "not_a_real_field": 1})


def test_divergence_plan_and_findings_serialize() -> None:
    plan = DivergencePlan.isolate("characters")
    bible = StoryBible(
        mode=GenerationMode.FROM_SOURCE,
        source_excerpt_path="source.txt",
        divergence_plan=plan,
        originality_findings=[
            OriginalityFinding(category="resemblance", description="test", resolved=False)
        ],
    )
    restored = StoryBible.model_validate_json(bible.model_dump_json())
    assert restored.divergence_plan is not None
    assert restored.divergence_plan.per_dimension["characters"] is DivergenceIntensity.CLOSE
    assert restored.divergence_plan.per_dimension["plot"] is DivergenceIntensity.DIVERGENT
    assert restored.originality_findings[0].category == "resemblance"

def test_divergence_plan_isolate_covers_all_dimensions() -> None:
    plan = DivergencePlan.isolate("plot")
    assert plan.is_complete()
    assert plan.missing_dimensions() == []
    assert plan.per_dimension["plot"] is DivergenceIntensity.CLOSE
    assert all(
        plan.per_dimension[d] is DivergenceIntensity.DIVERGENT for d in PSALM_DIMENSIONS if d != "plot"
    )


def test_divergence_plan_isolate_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError):
        DivergencePlan.isolate("not_a_real_dimension")


def test_divergence_plan_uniform() -> None:
    plan = DivergencePlan.uniform(DivergenceIntensity.MODERATE)
    assert plan.is_complete()
    assert set(plan.per_dimension.values()) == {DivergenceIntensity.MODERATE}


def test_divergence_plan_incomplete_reports_missing() -> None:
    plan = DivergencePlan(per_dimension={"characters": DivergenceIntensity.CLOSE})
    assert plan.is_complete() is False
    assert "plot" in plan.missing_dimensions()


def test_evaluate_fidelity_no_mismatches_when_achieved_matches_intended() -> None:
    plan = DivergencePlan.isolate("characters")
    achieved = dict(plan.per_dimension)
    assert evaluate_fidelity(plan, achieved) == []


def test_evaluate_fidelity_flags_minor_and_major_mismatches() -> None:
    plan = DivergencePlan.uniform(DivergenceIntensity.DIVERGENT)
    achieved = {
        "writing_style": DivergenceIntensity.LOOSE,  # 1 step off -> minor
        "characters": DivergenceIntensity.CLOSE,  # 3 steps off -> major
        "plot": DivergenceIntensity.DIVERGENT,  # matches -> no mismatch
        "narrative_voice": DivergenceIntensity.DIVERGENT,
        "scenes": DivergenceIntensity.DIVERGENT,
        "world_building": DivergenceIntensity.DIVERGENT,
    }
    mismatches = evaluate_fidelity(plan, achieved)
    by_dim = {m.dimension: m for m in mismatches}
    assert by_dim["writing_style"].severity == "minor"
    assert by_dim["characters"].severity == "major"
    assert "plot" not in by_dim

