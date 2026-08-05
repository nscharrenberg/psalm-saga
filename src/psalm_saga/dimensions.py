from dataclasses import dataclass
from enum import StrEnum
from typing import Self, Literal, Sequence

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

PSALM_DIMENSIONS: tuple[str, ...] = (
    "writing_style",
    "narrative_voice",
    "characters",
    "plot",
    "scenes",
    "world_building",
)


class LengthTier(StrEnum):
    """How long a generated story should be, in chapters and target word count."""
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass(frozen=True)
class LengthTierSpec:
    min_chapters: int
    max_chapters: int
    target_total_words: int


LENGTH_TIER_SPECS: dict[LengthTier, LengthTierSpec] = {
    LengthTier.SHORT: LengthTierSpec(min_chapters=1, max_chapters=1, target_total_words=2_000),
    LengthTier.MEDIUM: LengthTierSpec(min_chapters=6, max_chapters=10, target_total_words=20_000),
    LengthTier.LONG: LengthTierSpec(min_chapters=25, max_chapters=35, target_total_words=90_000),
}

IsolationStrategy = Literal["isolate_preserve", "isolate_vary"]

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

class DivergenceIntensity(StrEnum):
    """How closely a generated story's treatment of one dimension should/does track the source.

    Ordered from most to least similar -- see :data:`DIVERGENCE_ORDER` for the numeric ordering
    used to measure how far an *achieved* level is from an *intended* one.
    """

    IDENTICAL = "identical"
    """Near-verbatim reuse of this dimension's content. Rarely a real generation goal -- mostly
    useful as an extreme positive-control point when benchmarking a detector."""

    CLOSE = "close"
    """Strongly similar: same core choices, only surface-level variation."""

    MODERATE = "moderate"
    """Recognizably related, but with real, substantive changes."""

    LOOSE = "loose"
    """Only faint or structural resemblance remains."""

    DIVERGENT = "divergent"
    """Deliberately different; not meant to resemble the source on this dimension at all."""


#: Numeric ordering of DivergenceIntensity, most to least similar. Used to measure the distance
#: between an intended and an achieved level (see :func:`evaluate_fidelity`).
DIVERGENCE_ORDER: tuple[DivergenceIntensity, ...] = (
    DivergenceIntensity.IDENTICAL,
    DivergenceIntensity.CLOSE,
    DivergenceIntensity.MODERATE,
    DivergenceIntensity.LOOSE,
    DivergenceIntensity.DIVERGENT,
)


class DivergencePlan(BaseModel):
    """
    Only used in from_source mode: the intended similarity level, per PSALM dimension.

    This is what makes the generated story usable as a PSALM evaluation counterpart -- and, at
    scale, as a benchmarking dataset: the plan is the ground-truth label a PSALM score should be
    checked against, dimension by dimension, rather than a single overall "similar or not".
    """
    model_config = ConfigDict(extra="forbid")

    per_dimension: dict[str, DivergenceIntensity] = Field(
        default_factory=dict,
        description="PSALM dimension name (see PSALM_DIMENSIONS) -> intended similarity level.",
    )

    notes: str = ""

    def is_complete(self) -> bool:
        """True once every PSALM dimension has an intended level recorded."""
        return all(dim in self.per_dimension for dim in PSALM_DIMENSIONS)

    def missing_dimensions(self) -> list[str]:
        return [dim for dim in PSALM_DIMENSIONS if dim not in self.per_dimension]

    @classmethod
    def uniform(cls, level: DivergenceIntensity, *, notes: str = "") -> DivergencePlan:
        """A baseline plan: every dimension set to the same intended level."""
        return cls(per_dimension={dim: level for dim in PSALM_DIMENSIONS}, notes=notes)

    @classmethod
    def isolate(
        cls,
        dimension: str,
        *,
        near: DivergenceIntensity = DivergenceIntensity.CLOSE,
        far: DivergenceIntensity = DivergenceIntensity.DIVERGENT,
        notes: str = "",
    ) -> DivergencePlan:
        """A plan holding one dimension at ``near`` and every other dimension at ``far``.

        This is the "does PSALM detect infringement on *this dimension alone*" test point: e.g.
        ``DivergencePlan.isolate("characters")`` keeps characters close to the source while
        deliberately diverging plot, world-building, voice, style, and scenes.
        """
        if dimension not in PSALM_DIMENSIONS:
            raise ValueError(f"Unknown PSALM dimension: \"{dimension!r}\". Expected one of \"{PSALM_DIMENSIONS}\".")

        plan = {dim: (near if dim == dimension else far) for dim in PSALM_DIMENSIONS}
        return cls(per_dimension=plan, notes=notes)


class FidelityMismatch(BaseModel):
    """One dimension where the finished story didn't land where the divergence plan intended."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    intended: DivergenceIntensity
    achieved: DivergenceIntensity
    severity: str = Field(description="'minor' (one step off) or 'major' (two+ steps off).")

def evaluate_fidelity(
    plan: DivergencePlan, achieved: dict[str, DivergenceIntensity]
) -> list[FidelityMismatch]:
    """Compare intended vs. achieved divergence levels and flag mismatches.

    A dataset item where the writer failed to actually hit its intended similarity level has a
    silently wrong ground-truth label -- this is the deterministic check that catches that before
    the item goes into a benchmarking manifest, rather than trusting the editor subagent's own
    self-report of "yes, I diverged this enough" at face value.
    """
    mismatches: list[FidelityMismatch] = []

    for dim, intended_level in plan.per_dimension.items():
        if dim not in achieved:
            continue

        achieved_level = achieved[dim]

        if achieved_level == intended_level:
            continue

        distance = abs(DIVERGENCE_ORDER.index(intended_level) - DIVERGENCE_ORDER.index(achieved_level))
        severity = "major" if distance >= 2 else "minor"

        mismatches.append(
            FidelityMismatch(
                dimension=dim, intended=intended_level, achieved=achieved_level, severity=severity
            )
        )

    return mismatches

def build_isolation_matrix(
        *,
        dimensions: Sequence[str] = PSALM_DIMENSIONS,
        strategy: IsolationStrategy = "isolate_preserve",
        near: DivergenceIntensity = DivergenceIntensity.CLOSE,
        far: DivergenceIntensity = DivergenceIntensity.DIVERGENT,
        include_baselines: bool = True,
) -> dict[str, DivergencePlan]:
    """
    Builds an isolation matrix based on specified dimensions, strategy, and divergence intensities.
    ``variant name -> DivergencePlan`` mapping: one variant per dimension, plus baselines

    This function generates a dictionary of divergence plans for the given dimensions using the specified
    strategy. It includes optional baseline divergence plans that apply uniform intensity across all
    dimensions. The isolation strategy determines how intensities near or far are applied to the specified
    dimensions.

    :param dimensions: A sequence of strings representing the dimensions for which divergence plans will be
        created. Each dimension must be a valid entry from `PSALM_DIMENSIONS`.
    :type dimensions: Sequence[str]
    :param strategy: Strategy to use for creating divergence plans. Valid strategies are
        "isolate_preserve" or "isolate_vary".
    :type strategy: IsolationStrategy
    :param near: The divergence intensity level considered as "close" for dimensions.
    :type near: DivergenceIntensity
    :param far: The divergence intensity level considered as "divergent" for dimensions.
    :type far: DivergenceIntensity
    :param include_baselines: Flag indicating whether to include baseline divergence plans
        (close and divergent variants for all dimensions uniformly).
    :type include_baselines: bool
    :return: A dictionary where keys are strings representing the divergence plan names, and values
        are `DivergencePlan` objects corresponding to the generated isolation matrix.
    :rtype: dict[str, DivergencePlan]
    """
    variants: dict[str, DivergencePlan] = {}

    for dim in dimensions:
        if dim not in PSALM_DIMENSIONS:
            raise ValueError(f"Unknown PSALM dimension: \"{dim!r}\". Expected one of \"{PSALM_DIMENSIONS}\".")

        if strategy == "isolate_preserve":
            variants[f"isolate_{dim}"] = DivergencePlan.isolate(dim, near=near, far=far)
        elif strategy == "isolate_vary":
            variants[f"vary_only_{dim}"] = DivergencePlan.isolate(dim, near=far, far=near)
        else:
            raise ValueError(f"Unknown strategy: {strategy!r}")

    if include_baselines:
        variants["baseline_all_close"] = DivergencePlan.uniform(near)
        variants["baseline_all_divergent"] = DivergencePlan.uniform(far)

    return variants


class ChapterStatus(StrEnum):
    PLANNED = "planned"
    DRAFTED = "drafted"
    APPROVED = "approved"


class Chapter(BaseModel):
    """One entry in the book's chapter outline, written by chapter-planner-agent and updated by
    writer-agent/chapter-reviewer-agent as it moves through the per-chapter writing loop."""
    model_config = ConfigDict(extra="forbid")

    index: int
    title: str = ""
    planned_summary: str = Field(
        default="",
        description="chapter-planner-agent's intended beats for this chapter.",
    )
    actual_summary: str = Field(
        default="",
        description=(
            "Filled in by chapter-reviewer-agent once the chapter is approved: what actually "
            "happens in the finished prose (can drift from planned_summary). This, not the plan, "
            "is what later chapters read for continuity."
        ),
    )
    target_word_count: int = 0
    characters_present: list[str] = Field(default_factory=list)
    status: ChapterStatus = ChapterStatus.PLANNED
    revision_count: int = 0


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
    length_tier: LengthTier = LengthTier.LONG
    chapters: list[Chapter] = Field(default_factory=list)

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
    achieved_divergence: dict[str, DivergenceIntensity] = Field(
        default_factory=dict,
        description=(
            "Filled in by the editor subagent's fidelity check: what similarity level the "
            "finished story actually landed on per dimension, for comparison against "
            "divergence_plan.per_dimension via evaluate_fidelity()."
        ),
    )
    fidelity_notes: str = ""

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