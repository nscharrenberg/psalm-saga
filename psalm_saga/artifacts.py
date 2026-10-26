"""Typed artifacts passed between stages. Each is persisted as JSON in the run directory,
so any stage can be inspected, edited by hand (or in the web app) and re-run from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------- source analysis


class ChapterInfo(BaseModel):
    index: int
    title: str = ""
    word_count: int = 0


class TextKind(BaseModel):
    """What kind of text the source is, which decides which measures apply to it."""

    kind: Literal["narrative", "essay", "letters", "drama", "poetry", "other"] = Field(
        "narrative", description="narrative: a story with characters and events; essay: argument, treatise, sermon, "
        "pamphlet; letters: correspondence; drama: a play; poetry: verse that is not mainly a story.")
    narrator: Literal["first", "second", "third", "mixed", "none"] = "third"
    has_cast: bool = Field(True, description="Does the text follow recurring characters through events and scenes?")
    note: str = ""


class SourceProfile(BaseModel):
    """Deterministic facts about the input — computed, never generated."""

    language: str
    language_confidence: float
    word_count: int
    chapters: list[ChapterInfo]
    stylometrics: dict[str, float]
    shape: dict = Field(default_factory=dict, description="Rhythm distribution (quantiles); numbers only.")
    form: dict = Field(default_factory=dict, description="Text form (prose / verse / drama) and its measures.")


class VarietyMarker(BaseModel):
    variety_form: str = Field(description="A single word or short form as the variety spells/uses it, e.g. 'mensch'.")
    standard_form: str = Field("", description="Its contemporary standard equivalent, e.g. 'mens'. Empty if none.")
    feature: str = Field("", description="The feature it illustrates, e.g. 'pre-1947 spelling -sch'.")


class CharacterVariety(BaseModel):
    character: str
    description: str = Field(description="How this character's speech differs from the narration.")


class LanguageVariety(BaseModel):
    """The variety a text is written in: period, region, dialect, spelling system."""

    standard: bool = Field(True, description="True if the text is in contemporary standard language.")
    name: str = Field("", description="e.g. '19th-century Dutch, De Vries-Te Winkel spelling' or 'Scots dialect'.")
    scope: str = Field("narration and dialogue", description="'narration and dialogue', 'dialogue only' or 'specific characters'.")
    description: str = Field("", description="Spelling system, inflection, syntax, vocabulary, forms of address.")
    character_varieties: list[CharacterVariety] = Field(default_factory=list)
    markers: list[VarietyMarker] = Field(default_factory=list)
    source_share: float | None = Field(None, description="Computed: share of variety forms in the source.")

    def render(self) -> str:
        if self.standard:
            return ""
        lines = [f"## Language variety (keep it): {self.name}", f"Scope: {self.scope}.", self.description]
        lines += [f"- {c.character}: {c.description}" for c in self.character_varieties]
        if self.markers:
            lines.append("Forms to use (variety form, not the modern standard form):")
            lines += [f"- {m.variety_form} (not: {m.standard_form})" if m.standard_form else f"- {m.variety_form}"
                      for m in self.markers[:30]]
        return "\n".join(x for x in lines if x)


class SceneNote(BaseModel):
    summary: str = Field(description="What happens in the scene, 1-3 sentences.")
    setting: str = Field("", description="Where and when.")
    characters: list[str] = Field(default_factory=list, description="Names of characters present.")
    purpose: str = Field("", description="Narrative function of the scene.")
    pov: str = Field("", description="Whose perspective, if identifiable.")
    location: str = Field("", description="Name of the place entity where the scene happens, if it is named.")


Gender = Literal["female", "male", "nonbinary", "unknown"]


class EntityNote(BaseModel):
    name: str
    kind: Literal["character", "place", "object", "organisation", "other"] = "character"
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    role: str = Field("", description="Narrative function (protagonist, mentor, ...). Characters only.")
    gender: Gender = Field(
        "unknown", description="Characters only: the gender the text presents (pronouns, forms of address); unknown if unclear.")


class RelationNote(BaseModel):
    source: str
    target: str
    type: str = Field(description="e.g. mother-of, rival, employer, loves")
    description: str = ""


class EventNote(BaseModel):
    description: str
    characters: list[str] = Field(default_factory=list)
    caused_by: str = Field("", description="The earlier event or motive that causes this one, if any.")
    cause_index: int | None = Field(None, description="0-based index of the earlier event in this list that causes it, if any.")
    location: str = Field("", description="Name of the place entity where it happens, if named.")


class ChunkNotes(BaseModel):
    """Extraction from one chunk of the source (the 'map' step)."""

    summary: str
    scenes: list[SceneNote] = Field(default_factory=list)
    entities: list[EntityNote] = Field(default_factory=list)
    relations: list[RelationNote] = Field(default_factory=list)
    events: list[EventNote] = Field(default_factory=list)
    style: str = Field("", description="Observations on writing style and narrative voice, in your own words.")


# ----------------------------------------------------------------- story bible (KB)


class Entity(BaseModel):
    id: str
    name: str
    kind: str = "character"
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    role: str = ""
    chapters: list[int] = Field(default_factory=list)
    mentions: int = 0
    gender: Gender = "unknown"


class Relation(BaseModel):
    source: str  # entity id
    target: str
    type: str
    description: str = ""


class ChapterSummary(BaseModel):
    index: int
    title: str = ""
    summary: str
    word_count: int = 0
    scenes: list[SceneNote] = Field(default_factory=list)
    events: list[EventNote] = Field(default_factory=list)


class Bible(BaseModel):
    """A knowledge base of the story: who, where, what happens, in which chapter."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    chapters: list[ChapterSummary] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)

    def entity(self, key: str) -> Entity | None:
        k = key.strip().lower()
        for e in self.entities:
            if e.id == key or e.name.lower() == k or k in (a.lower() for a in e.aliases):
                return e
        return None

    def characters(self) -> list[Entity]:
        return [e for e in self.entities if e.kind == "character"]

    def render(self, *, chapter: int | None = None, names: list[str] | None = None, max_entities: int = 40) -> str:
        """Prompt rendering, optionally scoped to one chapter's cast."""
        ents = self.entities
        if names:
            wanted = {n.lower() for n in names}
            ents = [e for e in ents if e.name.lower() in wanted or wanted & {a.lower() for a in e.aliases}] or ents
        elif chapter is not None:
            ents = [e for e in ents if chapter in e.chapters] or ents
        ents = sorted(ents, key=lambda e: -e.mentions)[:max_entities]
        ids = {e.id for e in ents}
        lines = ["# Entities"]
        for e in ents:
            alias = f" (also: {', '.join(e.aliases)})" if e.aliases else ""
            role = f" — {e.role}" if e.role else ""
            gender = f", {e.gender}" if e.kind == "character" and e.gender != "unknown" else ""
            lines.append(f"- {e.name}{alias} [{e.kind}{gender}{role}]: {e.description}")
        rels = [r for r in self.relations if r.source in ids and r.target in ids]
        if rels:
            name = {e.id: e.name for e in self.entities}
            lines.append("# Relations")
            lines += [f"- {name.get(r.source, r.source)} —{r.type}→ {name.get(r.target, r.target)}"
                      + (f": {r.description}" if r.description else "") for r in rels]
        return "\n".join(lines)


# ----------------------------------------------------------------- spec


class SubSpec(BaseModel):
    key: str = Field(description="Sub-dimension key from the taxonomy.")
    value: str = Field(description="The concrete, specific choice. Behaviour and mechanism, not labels.")
    evidence: str = Field("", description="Source mode: what in the source supports this (paraphrased). Else empty.")


class DimensionSpec(BaseModel):
    dimension: str
    summary: str = Field(description="One or two sentences capturing the dimension as a whole.")
    items: list[SubSpec]
    policy: str = "preserve"


class Spec(BaseModel):
    language: str
    title: str = ""
    logline: str = ""
    target_words: int
    chapters: int
    dimensions: list[DimensionSpec]
    notes: str = ""
    variety: LanguageVariety | None = None  # the language variety the story prose must be written in

    def dim(self, key: str) -> DimensionSpec | None:
        return next((d for d in self.dimensions if d.dimension == key), None)

    def render(self, only: list[str] | None = None) -> str:
        lines = [f"# Specification: {self.title}".rstrip(": "), f"Logline: {self.logline}",
                 f"Length: ~{self.target_words} words in {self.chapters} chapter(s)."]
        for d in self.dimensions:
            if only and d.dimension not in only:
                continue
            lines.append(f"\n## {d.dimension} ({d.policy})\n{d.summary}")
            lines += [f"- [{i.key}] {i.value}" for i in d.items]
        if self.variety and not self.variety.standard and (not only or "writing_style" in only):
            lines.append("\n" + self.variety.render())
        if self.notes:
            lines.append(f"\nNotes: {self.notes}")
        return "\n".join(lines)


# ----------------------------------------------------------------- transform


class Rename(BaseModel):
    original: str
    new: str
    kind: str = "character"
    note: str = Field("", description="Why the new name fits (gender, class, culture, period, connotation).")


class TransformMap(BaseModel):
    renames: list[Rename] = Field(default_factory=list)
    setting_shift: str = Field("", description="How the concrete setting is re-invented (if at all).")
    notes: str = ""

    def as_dict(self) -> dict[str, str]:
        return {r.original: r.new for r in self.renames if r.original and r.new}


# ----------------------------------------------------------------- plan


class ScenePlan(BaseModel):
    summary: str
    setting: str = ""
    characters: list[str] = Field(default_factory=list)
    beats: list[str] = Field(default_factory=list, description="3-7 concrete beats in order.")
    purpose: str = ""
    target_words: int = 0


class ChapterPlan(BaseModel):
    index: int
    title: str = Field("", description="Chapter title in the output language, without a 'Chapter N' prefix.")
    summary: str = ""
    pov: str = ""
    target_words: int = 0
    scenes: list[ScenePlan] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list, description="Spec commitments this chapter must visibly realise.")
    ends_with: str = Field("", description="State of things at chapter end, for continuity.")


class Outline(BaseModel):
    title: str
    arc: str = Field(description="The whole-story arc in a short paragraph.")
    chapters: list[ChapterPlan] = Field(description="Chapter skeletons: index, title, summary, pov, target_words.")


class Plan(BaseModel):
    title: str
    arc: str
    chapters: list[ChapterPlan]


# ----------------------------------------------------------------- drafting & review


class ChapterDraft(BaseModel):
    index: int
    title: str
    text: str
    word_count: int
    language: str
    attempts: int = 1
    recap: str = ""  # short summary of what was actually written, for downstream continuity


class Issue(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    origin: Literal["prose", "plan", "spec", "bible"] = Field(
        "prose", description="Where the problem comes from: prose = the chapter fails a sound plan; plan = the chapter "
        "follows its plan but the plan is wrong; spec / bible = plan and chapter follow the specification or story "
        "bible, which are themselves contradictory or wrong.")
    dimension: str = ""
    commitment: str = Field(description="The specific plan/spec commitment that is violated.")
    evidence: str = Field(description="Short paraphrase or <=12-word quote from the chapter showing the problem.")
    fix: str = Field(description="A concrete, local fix.")


class CoverageItem(BaseModel):
    id: str = Field(description="The checklist item's id, e.g. E2 or R1.")
    status: Literal["realised", "missing", "contradicted"] = Field(
        description="realised: the chapter shows it (in any wording); missing: not in the chapter; contradicted: "
        "the chapter says otherwise.")
    in_plan: bool = Field(True, description="Does the chapter plan include this item?")
    evidence: str = Field("", description="For missing or contradicted items: short evidence from the chapter.")


class ChapterReview(BaseModel):
    index: int = 0
    issues: list[Issue] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    strengths: str = ""

    def blocking(self, threshold: str = "major") -> list[Issue]:
        order = {"blocker": 0, "major": 1, "minor": 2}
        return [i for i in self.issues if order[i.severity] <= order[threshold]]


class Recap(BaseModel):
    recap: str = Field(description="3-6 sentences: what actually happened in the chapter, who knows what now.")
