from pathlib import Path
from typing import Any

import pytest

from psalm_saga.config import Settings  # type: ignore[import-untyped]
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    Character,
    DimensionField,
    GenerationMode,
    GrammaticalPerson,
    NarratorKnowledge,
    NarrativeVoice,
    PlotArchitecture,
    Scene,
    StoryBible,
    WorldBuilding,
    WritingStyle,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path / "sessions")


def _settled(value: str) -> DimensionField:
    return DimensionField(value=value, settled=True)


def build_fully_settled_bible(**overrides: Any) -> StoryBible:
    """A StoryBible with every field the full-settlement gate checks marked settled.

    Shared by test_dimensions.py and test_gate_tool.py so both don't repeat the same
    dozens-of-fields construction just to get a bible `is_ready_for_writing()` accepts.
    """
    defaults: dict[str, Any] = dict(
        mode=GenerationMode.FROM_SCRATCH,
        premise="A lighthouse keeper starts receiving letters addressed to the drowned.",
        writing_style=WritingStyle(
            register=_settled("plain, unadorned"),
            sentence_rhythm=_settled("short, declarative"),
            lexical_density=_settled("sparse"),
            figurative_language=_settled("sparing, maritime imagery only"),
            tone=_settled("quietly haunted"),
            dialogue_style=_settled("clipped, few words wasted"),
        ),
        narrative_voice=NarrativeVoice(
            person=GrammaticalPerson.THIRD,
            narrator_knowledge=NarratorKnowledge.LIMITED,
            narrative_distance=_settled("close"),
            narrative_presence=_settled("unobtrusive"),
            focalisation=_settled("Mara only"),
            temporal_perspective=_settled("past tense, linear"),
            reader_engagement=_settled("dread, then tenderness"),
        ),
        characters=[
            Character(
                name="Mara",
                role=_settled("protagonist"),
                external_goal=_settled("find out who is sending the letters"),
                internal_need=_settled("permission to grieve"),
                flaw=_settled("hoards other people's secrets instead of her own"),
                arc=_settled("learns to deliver the letters instead of hiding them"),
                voice_notes=_settled("terse, avoids the subject directly"),
                backstory=_settled("lost her brother to the same water years ago"),
            )
        ],
        plot=PlotArchitecture(
            structure=_settled("three-act"),
            inciting_incident=_settled("a letter arrives addressed to someone still alive"),
            climax=_settled("Mara delivers the letter she was told to burn"),
            resolution=_settled("the letters stop; she keeps the last one for herself"),
        ),
        scenes=[
            Scene(
                id="scene-1",
                setting=_settled("the lighthouse's lamp room, night"),
                sensory_details=_settled("wet rope, kerosene, the light's slow turn"),
                function=_settled("introduces the ritual of sorting mail no one should send"),
                tension=_settled("she almost doesn't open it"),
            )
        ],
        world_building=WorldBuilding(
            geography_and_space=_settled("a single lighthouse on a drowned stretch of coast"),
            rules_and_systems=_settled("the sea returns what it takes, addressed and stamped"),
            culture_and_society=_settled("a town that stopped asking where the mail comes from"),
            history_and_myth=_settled("a flood that took the town's dead and kept writing"),
        ),
    )
    defaults.update(overrides)
    return StoryBible(**defaults)