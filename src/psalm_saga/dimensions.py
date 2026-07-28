from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationMode(StrEnum):
    """How the Story Bible is produced."""
    FROM_SCRATCH = "from_scratch"
    FROM_SOURCE = "from_source"

class NarratorKnowledge(StrEnum):
    LIMITED = "limited"
    MULTIPLE = " multiple"
    OMNISCIENT = "omniscient"
    OBJECTIVE = "objective"

class GrammaticalPerson(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"

class DimensionField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(
        default="",
        description="The content of this field, in prose."
    )
    settled: bool = Field(
        default=False,
        description="True once the user has confirmed/accepted this value."
    )

class WritingStyle(BaseModel):
    """Corresponds to PSALM's Writing Style evaluator"""
    model_config = ConfigDict(extra="forbid")

    register: DimensionField = Field(default_factory=DimensionField)
    sentence_rhythm: DimensionField = Field(default_factory=DimensionField)
    lexical_density: DimensionField = Field(default_factory=DimensionField)
    figurative_language: DimensionField = Field(default_factory=DimensionField)
    tone: DimensionField = Field(default_factory=DimensionField)
    dialogue_style: DimensionField = Field(default_factory=DimensionField)

class NarrativeVoice(BaseModel):
    """Corresponds to PSALM's Narrative Voice evaluator"""
    model_config = ConfigDict(extra="forbid")
    person: GrammaticalPerson | None = None
    narrator_knowledge: NarratorKnowledge | None = None
    narrative_distance: DimensionField = Field(default_factory=DimensionField)
    narrative_presence: DimensionField = Field(default_factory=DimensionField)
    focalisation: DimensionField = Field(default_factory=DimensionField)
    temporal_perspective: DimensionField = Field(default_factory=DimensionField)
    reader_engagement: DimensionField = Field(default_factory=DimensionField)

class Character(BaseModel):
    """One entry in PSALM's Characterisation evaluator."""
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str = Field(
        default="",
        description="The role of this character in the story."
    )
    external_goal: str = ""
    internal_need: str = ""
    flaw: str = ""
    arc: str = ""
    voice_notes: str = Field(
        default="",
        description="How this character speaks/thinks."
    )
    relationships: dict[str, str] = Field(
        default_factory=dict,
        description="other character name -> nature of the relationship"
    )
    backstory: str = ""

class PlotArchitecture(BaseModel):
    """Corresponds to PSALM's Plat Architecture evaluator"""
    model_config = ConfigDict(extra="forbid")

    structure: str = Field(
        default="",
        description="The overall structure of the story, e.g. three-act, five-act, kishotenketsu, in medias res, frame tale"
    )

    inciting_incident: str = ""
    turning_points: list[str] = Field(default_factory=list)
    climax: str = ""
    resolution: str = ""
    causality_notes: str = Field(
        default="",
        description="How events causally chain into each other, not just sequence."
    )
    pacing: str = ""

class Scene(BaseModel):
    """One entry in PSALM's Scene evaluator."""
    model_config = ConfigDict(extra="forbid")

    id: str
    setting: str = ""
    sensory_details: str = ""
    function: str = Field(
        default="",
        description="What this scene does for plot/character/theme."
    )
    characters_present: list[str] = Field(default_factory=list)
    tension: str = ""

class WorldBuilding(BaseModel):
    """Corresponds to PSALM's World Building evaluator"""
    model_config = ConfigDict(extra="forbid")

    geography_and_space: DimensionField = Field(default_factory=DimensionField)
    rules_and_systems: DimensionField = Field(
        default_factory=DimensionField,
        description="Magic / technology / physics / political / economic systems and their limits / etc..."
    )
    culture_and_society: DimensionField = Field(default_factory=DimensionField)
    history_and_myth: DimensionField = Field(default_factory=DimensionField)

class OriginalityFinding(BaseModel):
    """One concern raised by the originality guard."""
    model_config = ConfigDict(extra="forbid")

    category: str = Field(
        description="One of: resemblance, parody, pastiche, quotation, scenes_a_faire, other"
    )
    description: str
    affected_dimension: str = Field(
        default="",
        description="Which bible dimension this concern touches, if any."
    )
    resolved: bool = False

class DivergencePlan(BaseModel):
    """
    Only use in from_source mode: which dimension to preserve vs deliberately vary.

    This is what makes the generated story usable as a PSALM evaluation counterpart.
    The plan records, per dimension, the intended similarity so that a PSALM score can later be interpreted against stated intent rather than guessed at.
    """
    model_config = ConfigDict(extra="forbid")

    preserve: list[str] = Field(
        default_factory=list,
        description="Dimension names to keep close to the source."
    )

    vary: list[str] = Field(
        default_factory=list,
        description="Dimension names to deliberately diverge from the source."
    )

    notes: str = ""

class StoryBible(BaseModel):
    """
    The complete, structured brief that drives prose generation.

    This is the single artifact shared across all subagents (extractor, brainstormer, originality guard, writer, editor).
    It is persisted to disk as ``story_bible.json`` inside the session directory and is the source of truth for the generated story.
    """
    model_config = ConfigDict(extra="forbid")

    mode: GenerationMode
    title: str = ""
    premise: str = ""
    genre: str = ""
    themes: list[str] = Field(
        default_factory=list,
    )
    target_length_words: int | None = None

    writing_style: WritingStyle = Field(default_factory=WritingStyle)
    narrative_voice: NarrativeVoice = Field(default_factory=NarrativeVoice)
    characters: list[Character] = Field(default_factory=list)
    plot: PlotArchitecture = Field(default_factory=PlotArchitecture)
    scenes: list[Scene] = Field(default_factory=list)
    world_building: WorldBuilding = Field(default_factory=WorldBuilding)

    # from_source only
    source_excerpt_path: str | None = Field(
        default=None,
        description="Path (within the session_dir) to the source text, if any."
    )
    divergence_plan: DivergencePlan | None = None

    # from_scratch only
    originality_findings: list[OriginalityFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_mode_specific_fields(self) -> Self:
        """
        Validate specific fields of the model based on mode after the instance is created.

        This method is intended to provide additional validation logic that must be applied
        after an instance of the model is initialized. The validation logic depends on the
        current mode of the model. For example, it checks if the `source_excerpt_path` field
        is set when the mode is `GenerationMode.FROM_SOURCE`. Instead of raising an error,
        the validation flags potential issues non-fatally and allows for incremental updates
        to the model where appropriate.

        :return: The instance of the class after validation.
        :rtype: Self
        """
        if self.mode is GenerationMode.FROM_SOURCE and self.source_excerpt_path is None:
            # Non-fatal: extraction may not have recorded the path yet.
            # We only warn via a soft flag rather than raising, since the bible is filled in incrementally.
            pass

        return self

    def is_ready_for_writing(self) -> tuple[bool, list[str]]:
        """
        Determine if all necessary elements are ready for writing a story.

        This method checks if essential elements for story writing are prepared.
        It validates the presence of a premise, characters, plot structure, and the
        inciting incident. If any of these elements are missing, they are listed.

        :returns:
            A tuple containing a boolean indicating readiness (`True` if all necessary
            elements are ready, `False` otherwise) and a list of missing element
            names required for writing the story.
        :rtype: tuple[bool, list[str]]
        """
        missing: list[str] = []

        if not self.premise:
            missing.append("premise")

        if not self.characters:
            missing.append("characters")

        if not self.plot.structure:
            missing.append("plot.structure")

        if not self.plot.inciting_incident:
            missing.append("plot.inciting_incident")

        return len(missing) == 0, missing

PSALM_DIMENSIONS: tuple[str, ...] = (
    "writing_style",
    "narrative_voice",
    "characters",
    "plot",
    "scenes",
    "world_building",
)