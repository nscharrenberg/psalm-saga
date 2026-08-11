from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    LENGTH_TIER_SPECS,
    PSALM_DIMENSIONS,
    Chapter,
    ChapterStatus,
    Character,
    DimensionField,
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    LengthTierSpec,
    OriginalityFinding,
    StoryBible,
    build_isolation_matrix,
    evaluate_fidelity,
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
    assert "scenes" in missing
    assert "plot.structure" in missing
    assert "plot.climax" in missing
    assert "writing_style.tone" in missing
    assert "narrative_voice.person" in missing
    assert "world_building.geography_and_space" in missing


def test_is_ready_for_writing_false_with_only_the_old_minimal_fields_set() -> None:
    """Regression guard for the full-settlement fix: premise + one character + plot.structure/
    inciting_incident used to be enough to pass. It no longer is -- writing_style, narrative_voice,
    world_building, scenes, and the rest of plot/characters must be settled too."""
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A lighthouse keeper discovers the sea remembers everything it swallows.",
        characters=[Character(name="Mara", role=DimensionField(value="protagonist", settled=True))],
    )
    bible.plot.structure = DimensionField(value="three-act", settled=True)
    bible.plot.inciting_incident = DimensionField(
        value="A drowned bell washes ashore, still ringing.", settled=True
    )
    ready, missing = bible.is_ready_for_writing()
    assert ready is False
    assert "plot.climax" in missing
    assert "writing_style.tone" in missing


def test_is_ready_for_writing_true_once_everything_is_settled() -> None:
    from conftest import build_fully_settled_bible

    bible = build_fully_settled_bible()
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


def test_build_isolation_matrix_default_covers_every_dimension_plus_baselines() -> None:
    matrix = build_isolation_matrix()
    # one isolate_<dim> variant per PSALM dimension, plus two baselines
    assert len(matrix) == len(PSALM_DIMENSIONS) + 2
    for dim in PSALM_DIMENSIONS:
        assert f"isolate_{dim}" in matrix
    assert "baseline_all_close" in matrix
    assert "baseline_all_divergent" in matrix

    for dim in PSALM_DIMENSIONS:
        variant = matrix[f"isolate_{dim}"]
        assert variant.is_complete()
        assert variant.per_dimension[dim] is DivergenceIntensity.CLOSE
        others = [variant.per_dimension[d] for d in PSALM_DIMENSIONS if d != dim]
        assert all(level is DivergenceIntensity.DIVERGENT for level in others)

    assert set(matrix["baseline_all_close"].per_dimension.values()) == {DivergenceIntensity.CLOSE}
    assert set(matrix["baseline_all_divergent"].per_dimension.values()) == {DivergenceIntensity.DIVERGENT}


def test_build_isolation_matrix_isolate_vary_inverts_near_and_far() -> None:
    matrix = build_isolation_matrix(
        dimensions=["characters"], strategy="isolate_vary", include_baselines=False
    )
    assert list(matrix.keys()) == ["vary_only_characters"]
    variant = matrix["vary_only_characters"]
    assert variant.per_dimension["characters"] is DivergenceIntensity.DIVERGENT
    others = [variant.per_dimension[d] for d in PSALM_DIMENSIONS if d != "characters"]
    assert all(level is DivergenceIntensity.CLOSE for level in others)


def test_build_isolation_matrix_subset_of_dimensions_without_baselines() -> None:
    matrix = build_isolation_matrix(dimensions=["plot", "scenes"], include_baselines=False)
    assert set(matrix.keys()) == {"isolate_plot", "isolate_scenes"}


def test_build_isolation_matrix_custom_near_far_levels() -> None:
    matrix = build_isolation_matrix(
        dimensions=["plot"],
        near=DivergenceIntensity.IDENTICAL,
        far=DivergenceIntensity.LOOSE,
        include_baselines=False,
    )
    variant = matrix["isolate_plot"]
    assert variant.per_dimension["plot"] is DivergenceIntensity.IDENTICAL
    assert variant.per_dimension["characters"] is DivergenceIntensity.LOOSE


def test_build_isolation_matrix_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError):
        build_isolation_matrix(dimensions=["not_a_real_dimension"])


def test_build_isolation_matrix_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        build_isolation_matrix(dimensions=["plot"],
                               strategy="not_a_real_strategy")  # type: ignore[arg-type,unused-ignore]


def test_chapter_defaults_and_round_trips_through_json() -> None:
    chapter = Chapter(index=1, title="The First Letter")
    restored = Chapter.model_validate_json(chapter.model_dump_json())
    assert restored == chapter
    assert restored.status is ChapterStatus.PLANNED
    assert restored.revision_count == 0
    assert restored.characters_present == []


def test_story_bible_chapters_default_empty_and_length_tier_defaults_long() -> None:
    bible = StoryBible(mode=GenerationMode.FROM_SCRATCH)
    assert bible.chapters == []
    assert bible.length_tier is LengthTier.LONG


def test_story_bible_with_chapters_round_trips_through_json() -> None:
    bible = StoryBible(
        mode=GenerationMode.FROM_SCRATCH,
        length_tier=LengthTier.SHORT,
        chapters=[Chapter(index=1, title="Only Chapter", target_word_count=2000)],
    )
    restored = StoryBible.model_validate_json(bible.model_dump_json())
    assert restored.length_tier is LengthTier.SHORT
    assert restored.chapters[0].title == "Only Chapter"
    assert restored.chapters[0].status is ChapterStatus.PLANNED


def test_length_tier_specs_cover_every_tier_with_expected_ranges() -> None:
    assert set(LENGTH_TIER_SPECS) == {LengthTier.SHORT, LengthTier.MEDIUM, LengthTier.LONG}
    assert LENGTH_TIER_SPECS[LengthTier.SHORT] == LengthTierSpec(
        min_chapters=1, max_chapters=1, target_total_words=2_000
    )
    assert LENGTH_TIER_SPECS[LengthTier.MEDIUM] == LengthTierSpec(
        min_chapters=6, max_chapters=10, target_total_words=20_000
    )
    assert LENGTH_TIER_SPECS[LengthTier.LONG] == LengthTierSpec(
        min_chapters=25, max_chapters=35, target_total_words=90_000
    )
    for spec in LENGTH_TIER_SPECS.values():
        assert spec.min_chapters <= spec.max_chapters
