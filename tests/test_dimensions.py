import json

import pytest
from pydantic import ValidationError

from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    Character,
    DivergencePlan,
    GenerationMode,
    OriginalityFinding,
    StoryBible,
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
    bible = StoryBible(
        mode=GenerationMode.FROM_SOURCE,
        source_excerpt_path="source.txt",
        divergence_plan=DivergencePlan(preserve=["characters"], vary=["plot", "world_building"]),
        originality_findings=[
            OriginalityFinding(category="resemblance", description="test", resolved=False)
        ],
    )
    restored = StoryBible.model_validate_json(bible.model_dump_json())
    assert restored.divergence_plan is not None
    assert restored.divergence_plan.preserve == ["characters"]
    assert restored.originality_findings[0].category == "resemblance"
