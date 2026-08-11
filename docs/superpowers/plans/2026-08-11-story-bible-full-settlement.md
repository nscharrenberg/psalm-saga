# Story Bible Full Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `writer-agent`/`chapter-planner-agent` unreachable until every content field in `story_bible.json` is genuinely settled (or the user has explicitly overridden), while cutting down how many questions it takes to get there.

**Architecture:** Extend `DimensionField` settled-tracking to `Character`/`PlotArchitecture`/`Scene` (today only `WritingStyle`/`NarrativeVoice`/`WorldBuilding` have it), rewrite `StoryBible.is_ready_for_writing()` to walk every gated field instead of four hardcoded ones, add a deterministic `check_bible_readiness` tool (mirroring the existing `check_originality_gate` pattern) that the orchestrator must call before `chapter-planner-agent`, and add a `settlement_override` escape hatch for when the user explicitly chooses to proceed with gaps. Prompt changes teach `brainstorm-agent` to mine `--context` before asking, propose multi-field questions, and hand budget-exhaustion decisions back to the user instead of silently truncating settlement.

**Tech Stack:** Python 3.13, Pydantic v2, LangGraph/`deepagents`, `jsonpatchkit`, pytest.

## Global Constraints

- `DimensionField.settled` semantics (`{value: str, settled: bool}`) must stay exactly as defined in `src/psalm_saga/dimensions.py` — do not change its shape, only which fields use it.
- `story_bible.json` is only ever written through `update_story_bible` (RFC 6902 JSON Patch) — never add a new direct-write path.
- `mode` and `length_tier` are locked after the bible's first write (existing invariant in `bible.py`'s `update_story_bible`) — do not weaken this.
- Gated fields decided during brainstorming (do not re-litigate in this plan):
  - `Character`: `role`, `external_goal`, `internal_need`, `flaw`, `arc`, `voice_notes`, `backstory` gated. `name`, `relationships` ungated.
  - `PlotArchitecture`: `structure`, `inciting_incident`, `climax`, `resolution` gated. `turning_points`, `causality_notes`, `pacing` ungated.
  - `Scene`: `setting`, `sensory_details`, `function`, `tension` gated. `id`, `characters_present` ungated.
  - `premise` stays a required plain string (unchanged from today), not wrapped in `DimensionField`.
  - `title`, `themes`, `target_length_words`, `genre` stay ungated (writer's/chapter-planner's discretion), matching current behavior.
- No migration path for pre-existing `story_bible.json` files — sessions started before this lands are expected to be restarted (accepted limitation from the design doc).
- Since this plan landed, `writer-agent` is no longer the gate's destination — `chapter-planner-agent` is (the chapter-by-chapter generation feature shipped after the design doc was written; the design's "writer-agent" references mean "chapter-planner-agent, and therefore any prose generation" in this codebase's current shape).

---

### Task 1: Full-settlement schema and readiness gate

**Files:**
- Modify: `src/psalm_saga/dimensions.py`
- Modify: `src/psalm_saga/tools/bible.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_dimensions.py`
- Modify: `tests/test_bible_tool.py`
- Modify: `tests/test_update_story_bible.py`

**Interfaces:**
- Produces: `DimensionField`-typed `Character.role/external_goal/internal_need/flaw/arc/voice_notes/backstory`; `DimensionField`-typed `PlotArchitecture.structure/inciting_incident/climax/resolution`; `DimensionField`-typed `Scene.setting/sensory_details/function/tension`; `StoryBible.settlement_override: bool` and `StoryBible.settlement_override_reason: str`; rewritten `StoryBible.is_ready_for_writing() -> tuple[bool, list[str]]` returning dotted-path names (e.g. `"characters[0].arc"`, `"plot.climax"`, `"writing_style.tone"`). `build_fully_settled_bible(**overrides) -> StoryBible` helper in `tests/conftest.py`. Also updates `update_story_bible`'s tool docstring in `bible.py` (patch-shape examples only -- the status-message wording it returns is Task 3's job, not this task's).
- Consumes: nothing new from other tasks (this is the foundation task).

- [ ] **Step 1: Wrap `Character`/`PlotArchitecture`/`Scene` content fields in `DimensionField`**

Edit `src/psalm_saga/dimensions.py`. Replace the `Character` class body:

```python
class Character(BaseModel):
    """One entry in PSALM's Characterisation evaluator."""
    model_config = ConfigDict(extra="forbid")

    name: str
    role: DimensionField = Field(
        default_factory=DimensionField,
        description="The role of this character in the story."
    )
    external_goal: DimensionField = Field(default_factory=DimensionField)
    internal_need: DimensionField = Field(default_factory=DimensionField)
    flaw: DimensionField = Field(default_factory=DimensionField)
    arc: DimensionField = Field(default_factory=DimensionField)
    voice_notes: DimensionField = Field(
        default_factory=DimensionField,
        description="How this character speaks/thinks."
    )
    relationships: dict[str, str] = Field(
        default_factory=dict,
        description="other character name -> nature of the relationship"
    )
    backstory: DimensionField = Field(default_factory=DimensionField)
```

Replace `PlotArchitecture`:

```python
class PlotArchitecture(BaseModel):
    """Corresponds to PSALM's Plat Architecture evaluator"""
    model_config = ConfigDict(extra="forbid")

    structure: DimensionField = Field(
        default_factory=DimensionField,
        description="The overall structure of the story, e.g. three-act, five-act, kishotenketsu, in medias res, frame tale"
    )

    inciting_incident: DimensionField = Field(default_factory=DimensionField)
    turning_points: list[str] = Field(default_factory=list)
    climax: DimensionField = Field(default_factory=DimensionField)
    resolution: DimensionField = Field(default_factory=DimensionField)
    causality_notes: str = Field(
        default="",
        description="How events causally chain into each other, not just sequence."
    )
    pacing: str = ""
```

Replace `Scene`:

```python
class Scene(BaseModel):
    """One entry in PSALM's Scene evaluator."""
    model_config = ConfigDict(extra="forbid")

    id: str
    setting: DimensionField = Field(default_factory=DimensionField)
    sensory_details: DimensionField = Field(default_factory=DimensionField)
    function: DimensionField = Field(
        default_factory=DimensionField,
        description="What this scene does for plot/character/theme."
    )
    characters_present: list[str] = Field(default_factory=list)
    tension: DimensionField = Field(default_factory=DimensionField)
```

- [ ] **Step 2: Add `settlement_override` fields to `StoryBible`**

In `src/psalm_saga/dimensions.py`, in the `StoryBible` class, add these two fields right after `fidelity_notes: str = ""` and before the `# from_scratch only` comment:

```python
    # settlement gate (both modes)
    settlement_override: bool = False
    settlement_override_reason: str = ""
```

- [ ] **Step 3: Add gated-field constants and rewrite `is_ready_for_writing()`**

Still in `src/psalm_saga/dimensions.py`, add these module-level constants just above the `StoryBible` class:

```python
_CHARACTER_GATED_FIELDS: tuple[str, ...] = (
    "role", "external_goal", "internal_need", "flaw", "arc", "voice_notes", "backstory",
)
_PLOT_GATED_FIELDS: tuple[str, ...] = ("structure", "inciting_incident", "climax", "resolution")
_SCENE_GATED_FIELDS: tuple[str, ...] = ("setting", "sensory_details", "function", "tension")
_NARRATIVE_VOICE_DIMENSION_FIELDS: tuple[str, ...] = (
    "narrative_distance", "narrative_presence", "focalisation", "temporal_perspective",
    "reader_engagement",
)
```

Replace the body of `is_ready_for_writing`:

```python
    def is_ready_for_writing(self) -> tuple[bool, list[str]]:
        """
        Report whether every gated field in the bible is settled, and which ones aren't.

        A field counts as gated if it's one of the six PSALM dimensions' content fields (see
        the module-level `_..._GATED_FIELDS` constants for exactly which ones -- connective/
        reference fields like `turning_points` or `characters_present` are deliberately excluded).
        `premise` is checked separately since it isn't part of any PSALM dimension. `characters`
        and `scenes` also require at least one entry, not just settled entries once present.

        :returns: `(True, [])` once nothing is missing, else `(False, <dotted-path list>)` --
            e.g. `"characters[0].arc"`, `"plot.climax"`, `"writing_style.tone"` -- naming exactly
            which fields still need settling.
        :rtype: tuple[bool, list[str]]
        """
        missing: list[str] = []

        if not self.premise:
            missing.append("premise")

        for field_name in WritingStyle.model_fields:
            if not getattr(self.writing_style, field_name).settled:
                missing.append(f"writing_style.{field_name}")

        if self.narrative_voice.person is None:
            missing.append("narrative_voice.person")
        if self.narrative_voice.narrator_knowledge is None:
            missing.append("narrative_voice.narrator_knowledge")
        for field_name in _NARRATIVE_VOICE_DIMENSION_FIELDS:
            if not getattr(self.narrative_voice, field_name).settled:
                missing.append(f"narrative_voice.{field_name}")

        if not self.characters:
            missing.append("characters")
        else:
            for i, character in enumerate(self.characters):
                for field_name in _CHARACTER_GATED_FIELDS:
                    if not getattr(character, field_name).settled:
                        missing.append(f"characters[{i}].{field_name}")

        for field_name in _PLOT_GATED_FIELDS:
            if not getattr(self.plot, field_name).settled:
                missing.append(f"plot.{field_name}")

        if not self.scenes:
            missing.append("scenes")
        else:
            for i, scene in enumerate(self.scenes):
                for field_name in _SCENE_GATED_FIELDS:
                    if not getattr(scene, field_name).settled:
                        missing.append(f"scenes[{i}].{field_name}")

        for field_name in WorldBuilding.model_fields:
            if not getattr(self.world_building, field_name).settled:
                missing.append(f"world_building.{field_name}")

        return len(missing) == 0, missing
```

- [ ] **Step 4: Add a `build_fully_settled_bible` test helper to `tests/conftest.py`**

Append to `tests/conftest.py`:

```python
from typing import Any

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
```

- [ ] **Step 5: Update `tests/test_dimensions.py` for the new gate**

Replace `test_is_ready_for_writing_reports_missing_fields`:

```python
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
```

Replace `test_is_ready_for_writing_true_once_minimum_fields_set` with two tests -- one showing the old minimal bar is no longer sufficient, one showing a fully-settled bible passes:

```python
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
```

Add `DimensionField` to the existing `from psalm_saga.dimensions import (...)` block at the top of the file.

- [ ] **Step 6: Fix `tests/test_bible_tool.py`'s fixture for the new schema**

Replace the full body of `test_validate_reports_ok_when_ready` so it builds a fully-settled bible via the shared helper instead of the old four-field minimum:

```python
def test_validate_reports_ok_when_ready(tmp_path: Path) -> None:
    from conftest import build_fully_settled_bible

    bible = build_fully_settled_bible()
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    tool = make_validate_bible_tool(tmp_path)
    result = _invoke(tool)  # type: ignore[no-untyped-call]
    assert result.startswith("OK: story_bible.json is schema-valid and has the minimum fields")
```

(This step only fixes the fixture so the test still exercises a genuinely-ready bible under the new schema; the assertion text itself is updated in Task 3 once `bible.py`'s wording changes.)

- [ ] **Step 7: Fix `tests/test_update_story_bible.py`'s `Character` patch payloads**

Three call sites construct a character with a bare-string `role`, which the new schema rejects. In `test_append_to_a_list_via_dash_path`, change:

```python
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
```
to:
```python
            _op("add", "/characters/-", {"name": "Mara", "role": {"value": "protagonist", "settled": True}}),
```

and:
```python
    _invoke(tool, patch=[_op("add", "/characters/-", {"name": "Odile", "role": "antagonist"})])
```
to:
```python
    _invoke(tool, patch=[_op("add", "/characters/-", {"name": "Odile", "role": {"value": "antagonist", "settled": True}})])
```

In `test_stale_index_test_op_is_rejected_and_file_untouched`, change:
```python
            _op("add", "/characters/-", {"name": "Mara", "role": "protagonist"}),
```
to:
```python
            _op("add", "/characters/-", {"name": "Mara", "role": {"value": "protagonist", "settled": True}}),
```

- [ ] **Step 8: Fix the now-stale patch-shape examples in `update_story_bible`'s own docstring**

`src/psalm_saga/tools/bible.py`'s `update_story_bible` docstring is the primary usage guide every
agent with this tool reads -- it still shows `/plot/structure` and a character's `role` as plain
values, which Step 1 just turned into `DimensionField` objects. In
`src/psalm_saga/tools/bible.py`, change:

```python
        Each entry in `patch` is one operation: `{"op": "replace", "path": "/plot/structure",
        "value": "three-act"}` sets a field that already exists -- most StoryBible fields already
        exist with a schema default, so `replace` works for them from your first call. A field
        that's `None`/empty until first set (like `mode` on your very first call of a session, or
        a new key inside a dict field such as `/achieved_divergence/<dimension>`) needs `"add"`
        instead. Use `"add"` with a path ending in `/-` to append to a list, e.g. `{"op": "add",
        "path": "/characters/-", "value": {"name": "Finn", "role": "..."}}`. Use `"remove"` to
```
to:
```python
        Each entry in `patch` is one operation: `{"op": "replace", "path": "/premise",
        "value": "..."}` sets a plain scalar field that already exists -- most StoryBible fields
        already exist with a schema default, so `replace` works for them from your first call. A
        `DimensionField` (e.g. `plot.structure`, `writing_style.tone`, a character's `role`) is an
        object, not a plain value -- target its `.../value` and `.../settled` sub-paths
        separately, e.g. `{"op": "replace", "path": "/plot/structure/value", "value":
        "three-act"}` plus `{"op": "replace", "path": "/plot/structure/settled", "value": true}`
        once you're confident enough in it to mark it settled. A field that's `None`/empty until
        first set (like `mode` on your very first call of a session, or a new key inside a dict
        field such as `/achieved_divergence/<dimension>`) needs `"add"` instead. Use `"add"` with
        a path ending in `/-` to append to a list, e.g. `{"op": "add", "path": "/characters/-",
        "value": {"name": "Finn", "role": {"value": "...", "settled": false}}}`. Use `"remove"` to
```

- [ ] **Step 9: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (in particular `test_dimensions.py`, `test_bible_tool.py`, `test_update_story_bible.py`, and everything unrelated like `test_gate_tool.py`, `test_fidelity_tool.py`, `test_prompts.py` stay green -- they don't touch the fields changed here).

- [ ] **Step 10: Commit**

```bash
git add src/psalm_saga/dimensions.py src/psalm_saga/tools/bible.py tests/conftest.py tests/test_dimensions.py tests/test_bible_tool.py tests/test_update_story_bible.py
git commit -m "feat(dimensions): extend DimensionField settlement to characters/plot/scenes, require full settlement to write"
```

---

### Task 2: `check_bible_readiness` deterministic gate tool

**Files:**
- Modify: `src/psalm_saga/tools/gate.py`
- Modify: `src/psalm_saga/tools/__init__.py`
- Modify: `src/psalm_saga/agents/orchestrator.py`
- Modify: `tests/test_gate_tool.py`

**Interfaces:**
- Consumes: `StoryBible.is_ready_for_writing()` and `StoryBible.settlement_override`/`settlement_override_reason` (Task 1). `build_fully_settled_bible` from `tests/conftest.py` (Task 1).
- Produces: `make_check_bible_readiness_tool(session_dir: Path)` returning a `check_bible_readiness` tool, exported from `psalm_saga.tools`, wired into the orchestrator's own tool list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gate_tool.py` (add `StoryBible` is already imported; add `make_check_bible_readiness_tool` to the existing import from `psalm_saga.tools.gate`):

```python
from psalm_saga.tools.gate import (  # type: ignore[import-untyped,import-untyped]
    make_check_bible_readiness_tool,
    make_check_originality_gate_tool,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gate_tool.py -v`
Expected: FAIL with `ImportError: cannot import name 'make_check_bible_readiness_tool'`.

- [ ] **Step 3: Implement `make_check_bible_readiness_tool`**

Append to `src/psalm_saga/tools/gate.py` (after `make_check_originality_gate_tool`):

```python
def make_check_bible_readiness_tool(session_dir: Path):  # type: ignore[no-untyped-def]
    """Build a `check_bible_readiness` tool bound to one session's bible.

    Mirrors `make_check_originality_gate_tool`'s pattern: a deterministic PROCEED/BLOCKED verdict
    computed from `StoryBible.is_ready_for_writing()`, so the orchestrator's decision to hand off
    to `chapter-planner-agent` doesn't depend on the model correctly judging "is this settled" from
    a long JSON document itself.
    """
    bible_path = session_dir / "story_bible.json"

    @tool
    def check_bible_readiness() -> str:
        """Check whether story_bible.json is fully settled and ready for chapter-planner-agent.

        Call this before delegating to chapter-planner-agent, in both from_scratch and from_source
        mode. If it returns BLOCKED, do not delegate to chapter-planner-agent -- send the bible
        back to brainstorm-agent to settle the listed fields, then re-check. If it returns
        PROCEED (OVERRIDDEN), the user has explicitly chosen to proceed with the listed fields
        left unsettled -- continue, but surface the override and the unsettled list prominently in
        your final report.
        """
        if not bible_path.exists():
            return "BLOCKED: story_bible.json does not exist yet."

        try:
            bible = StoryBible.model_validate(json.loads(bible_path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the model, deliberately broad
            return f"BLOCKED: story_bible.json is not currently valid ({exc}). Fix it first."

        ready, missing = bible.is_ready_for_writing()
        if ready:
            return "PROCEED: story_bible.json is fully settled."

        summary = ", ".join(missing)

        if bible.settlement_override:
            reason = bible.settlement_override_reason or "(no reason recorded)"
            return (
                f"PROCEED (OVERRIDDEN): {len(missing)} field(s) still unsettled: {summary}. "
                f"User override reason: {reason}. Surface this prominently in your final report."
            )

        return f"BLOCKED: {len(missing)} field(s) still unsettled: {summary}."

    return check_bible_readiness
```

- [ ] **Step 4: Export it from `tools/__init__.py`**

In `src/psalm_saga/tools/__init__.py`, change:
```python
from psalm_saga.tools.gate import make_check_originality_gate_tool
```
to:
```python
from psalm_saga.tools.gate import make_check_bible_readiness_tool, make_check_originality_gate_tool
```
and add `"make_check_bible_readiness_tool"` to `__all__`.

- [ ] **Step 5: Wire it into the orchestrator**

In `src/psalm_saga/agents/orchestrator.py`, add `make_check_bible_readiness_tool` to the `from psalm_saga.tools import (...)` block, build it alongside the other gate tool:

```python
    check_bible_readiness = make_check_bible_readiness_tool(session_dir)
```

and add `check_bible_readiness` to the `tools=[...]` list passed to `create_deep_agent`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_gate_tool.py -v`
Expected: PASS, all 5 new tests plus the existing `check_originality_gate` tests.

- [ ] **Step 7: Commit**

```bash
git add src/psalm_saga/tools/gate.py src/psalm_saga/tools/__init__.py src/psalm_saga/agents/orchestrator.py tests/test_gate_tool.py
git commit -m "feat(gate): add check_bible_readiness tool, wire into orchestrator"
```

---

### Task 3: Update `bible.py` status wording for the new gate

**Files:**
- Modify: `src/psalm_saga/tools/bible.py`
- Modify: `tests/test_bible_tool.py`

**Interfaces:**
- Consumes: `StoryBible.is_ready_for_writing()` (Task 1, already returns dotted paths).
- Produces: no new interfaces -- this only changes the human/model-readable strings `update_story_bible` and `validate_story_bible` return.

- [ ] **Step 1: Update the two status messages**

In `src/psalm_saga/tools/bible.py`, in `update_story_bible`, change:
```python
        ready, missing = bible.is_ready_for_writing()
        status = "ready for the writer subagent" if ready else f"missing: {', '.join(missing)}"
        return f"OK: story_bible.json updated ({status})."
```
to:
```python
        ready, missing = bible.is_ready_for_writing()
        status = (
            "fully settled, ready for chapter-planner-agent" if ready
            else f"still unsettled: {', '.join(missing)}"
        )
        return f"OK: story_bible.json updated ({status})."
```

In `validate_story_bible`, change:
```python
        bible = outcome.validated
        ready, missing = bible.is_ready_for_writing()
        if ready:
            return "OK: story_bible.json is schema-valid and has the minimum fields for writing."
        return (
            "OK: story_bible.json is schema-valid, but not yet ready for the writer subagent. "
            f"Missing/empty required fields: {', '.join(missing)}."
        )
```
to:
```python
        bible = outcome.validated
        ready, missing = bible.is_ready_for_writing()
        if ready:
            return (
                "OK: story_bible.json is schema-valid and fully settled, ready for "
                "chapter-planner-agent."
            )
        return (
            "OK: story_bible.json is schema-valid, but not yet fully settled. "
            f"Still unsettled: {', '.join(missing)}."
        )
```

- [ ] **Step 2: Update the two assertions this wording change breaks**

In `tests/test_bible_tool.py`, in `test_validate_reports_missing_required_fields`, change:
```python
    assert "not yet ready" in result
```
to:
```python
    assert "not yet fully settled" in result
```

In `test_validate_reports_ok_when_ready` (already updated in Task 1 to use `build_fully_settled_bible`), change:
```python
    assert result.startswith("OK: story_bible.json is schema-valid and has the minimum fields")
```
to:
```python
    assert result.startswith("OK: story_bible.json is schema-valid and fully settled")
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_bible_tool.py tests/test_update_story_bible.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/psalm_saga/tools/bible.py tests/test_bible_tool.py
git commit -m "docs(bible): update readiness wording for full settlement and chapter-planner-agent handoff"
```

---

### Task 4: Wire `max_brainstorm_turns` into the orchestrator's system prompt

**Files:**
- Modify: `src/psalm_saga/agents/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Settings.max_brainstorm_turns` (already exists in `src/psalm_saga/config.py`).
- Produces: `_build_system_prompt(settings: Settings) -> str` in `src/psalm_saga/agents/orchestrator.py`, used by `build_orchestrator`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_orchestrator.py`:

```python
from psalm_saga.agents.orchestrator import _build_system_prompt  # type: ignore[import-untyped]
from psalm_saga.config import Settings  # type: ignore[import-untyped]


def test_system_prompt_includes_configured_max_brainstorm_turns() -> None:
    settings = Settings(model="anthropic:claude-opus-4-8", max_brainstorm_turns=55)
    prompt = _build_system_prompt(settings)
    assert "max_brainstorm_turns" in prompt
    assert "55" in prompt


def test_system_prompt_still_contains_the_base_orchestrator_prompt() -> None:
    settings = Settings(model="anthropic:claude-opus-4-8")
    prompt = _build_system_prompt(settings)
    assert "You are the orchestrator for PSALM-SAGA" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_system_prompt'`.

- [ ] **Step 3: Implement `_build_system_prompt` and use it in `build_orchestrator`**

In `src/psalm_saga/agents/orchestrator.py`, add this function above `build_orchestrator`:

```python
def _build_system_prompt(settings: Settings) -> str:
    """The orchestrator's system prompt plus session-specific configuration values.

    Prompts are loaded verbatim from static markdown (see `load_prompt`) with no templating, so
    settings like `max_brainstorm_turns` are otherwise invisible to the orchestrator at runtime --
    `orchestrator.md` tells it to pass this number to brainstorm-agent, but without this, there was
    no number to pass.
    """
    return load_prompt("orchestrator") + (
        "\n\n## Session configuration\n"
        f"- max_brainstorm_turns: {settings.max_brainstorm_turns}\n\n"
        "Pass the max_brainstorm_turns number above to brainstorm-agent in its delegation task "
        "every time you invoke it, so it knows its turn budget for that invocation."
    )
```

Change `build_orchestrator`'s `create_deep_agent` call from `system_prompt=load_prompt("orchestrator")` to `system_prompt=_build_system_prompt(settings)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/psalm_saga/agents/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): wire max_brainstorm_turns into the system prompt"
```

---

### Task 5: `orchestrator.md` -- readiness gate in both mode sequences, from_source settle-pass

**Files:**
- Modify: `src/psalm_saga/prompts/orchestrator.md`
- Modify: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `check_bible_readiness` tool name (Task 2), `max_brainstorm_turns` session-configuration text (Task 4).
- Produces: no code interfaces -- this is prompt content other tasks' agents (brainstorm-agent, in Task 6) are instructed to expect.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompts.py`:

```python
def test_orchestrator_prompt_calls_check_bible_readiness_before_chapter_planner() -> None:
    text = load_prompt("orchestrator")
    assert "check_bible_readiness" in text
    # must appear before the first chapter-planner-agent delegation in the from_scratch sequence
    assert text.index("check_bible_readiness") < text.index("chapter-planner-agent")


def test_orchestrator_prompt_from_source_settles_remaining_gaps_before_chapter_planner() -> None:
    text = load_prompt("orchestrator")
    from_source_section = text.split("## mode = from_source")[1].split("## General rules")[0]
    assert "check_bible_readiness" in from_source_section
    assert "settle" in from_source_section.lower()


def test_orchestrator_prompt_tells_orchestrator_to_pass_turn_budget_to_brainstorm_agent() -> None:
    text = load_prompt("orchestrator")
    assert "max_brainstorm_turns" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py -k "check_bible_readiness or settles_remaining or turn_budget" -v`
Expected: FAIL (the new instructions don't exist in `orchestrator.md` yet).

- [ ] **Step 3: Rewrite the from_scratch sequence**

In `src/psalm_saga/prompts/orchestrator.md`, replace the `## mode = from_scratch` sequence's steps 1-4 (everything from "Sequence:" through the old step 4, which delegated to `chapter-planner-agent` right after the originality gate) with:

```markdown
Sequence:
1. Delegate to `brainstorm-agent` to fill `story_bible.json` by conversing with the user, one
   question at a time, using the PSALM dimensions as your checklist. If the user supplied initial
   context, pass it along verbatim so the subagent doesn't re-ask what's already known. Also pass
   the `max_brainstorm_turns` value from your session configuration above, so it knows its turn
   budget for this invocation.
2. Call `check_bible_readiness`. If it returns BLOCKED, delegate back to `brainstorm-agent` with
   the specific unsettled fields it listed, then re-check -- repeat until it returns PROCEED or
   PROCEED (OVERRIDDEN). If it returns PROCEED (OVERRIDDEN), note the override and the still-
   unsettled fields for your final report, but continue to the next step regardless.
3. Delegate to `originality-guard` to review the finished bible for the four exception categories
   and for resemblance to known works. If it reports unresolved findings, send the bible back to
   `brainstorm-agent` with the specific findings to address, then re-check. Do this for at most
   the configured revision budget.
4. Call `check_originality_gate`. If it returns BLOCKED, do not delegate to
   `chapter-planner-agent` -- report the open findings to the user and ask how they want to
   proceed (they may accept the risk explicitly, in which case say so plainly in your final
   message; you cannot silently override the block yourself). If it returns PROCEED (with or
   without a warn-mode note on open findings), continue to the next step.
5. Delegate to `chapter-planner-agent` once, to turn the finalized bible into a chapter outline
   (`story_bible.json`'s `chapters` list) sized to the bible's `length_tier`.
```

Renumber the remaining from_scratch steps (the per-chapter loop, `assemble_draft`, `finalize_story`+editor-agent, and the final report) from 5/6/7/8 to 6/7/8/9, keeping their content unchanged -- only the leading numeral changes on each.

- [ ] **Step 4: Rewrite the from_source sequence**

Replace the `## mode = from_source` sequence's steps 1-2 (extractor-agent through the direct `chapter-planner-agent` delegation) with:

```markdown
Sequence:
1. Delegate to `extractor-agent` to read the source text (path given to you) and populate
   `story_bible.json` from it -- it settles what the source text clearly supports directly, and
   leaves the rest `settled: false` for the next step.
2. Determine what's still open: check `divergence_plan` completeness yourself (is every PSALM
   dimension present in `per_dimension`?) and call `check_bible_readiness` for the dimension
   content. These are two independent gaps -- either, both, or neither may be open.
   - If `divergence_plan` was already complete when you started (see above) and
     `check_bible_readiness` returns PROCEED or PROCEED (OVERRIDDEN), skip straight to step 4 --
     extraction alone left everything settled, there's nothing for `brainstorm-agent` to do.
   - Otherwise, delegate to `brainstorm-agent` scoped to whichever gap(s) are open: negotiate
     `divergence_plan` if it's incomplete (unless it was pre-set -- see above, that case never
     renegotiates), settle the remaining dimension fields `check_bible_readiness` listed if it
     returned BLOCKED, or both in the same delegation if both are open. Pass `max_brainstorm_turns`
     from your session configuration the same way as in from_scratch mode.
3. Call `check_bible_readiness` again. If it still returns BLOCKED, delegate back to
   `brainstorm-agent` with the specific unsettled fields, then re-check -- repeat until PROCEED or
   PROCEED (OVERRIDDEN). Note any override for your final report.
4. Delegate to `chapter-planner-agent` once, to turn the finalized bible into a chapter outline
   sized to the bible's `length_tier`.
```

Renumber the remaining from_source steps (the per-chapter loop, `assemble_draft`, `finalize_story`+editor-agent, the fidelity-check read, and the final report) from 3/4/5/6/7 to 5/6/7/8/9, keeping their content unchanged.

- [ ] **Step 5: Update the todo-list guidance's from_source skip note**

In the "Show your work" section near the top, the bullet "If from_source mode skips brainstorm-agent (a pre-set `divergence_plan`, see below), don't include that step in the todo list at all rather than adding it and marking it skipped" is still accurate (extraction-alone-sufficient is now a *rarer* case than before, but the same principle applies) -- leave it as-is.

- [ ] **Step 6: Fix the now-stale patch-shape example in the "General rules" section**

The "General rules" section's own explanation of `update_story_bible` patch syntax still shows
`/plot/structure` as a plain value, which Task 1 turned into a `DimensionField` object. Change:

```markdown
  directly rather than through a subagent (see the next rule, on when that's warranted). Patches
  are a list of RFC 6902 JSON Patch operations, not a whole object: `{"op": "replace", "path":
  "/plot/structure", "value": "three-act"}` sets a field that already has a value; `{"op": "add",
  "path": "/characters/-", "value": {...}}` appends to a list (same `/-` pattern for other list
```
to:
```markdown
  directly rather than through a subagent (see the next rule, on when that's warranted). Patches
  are a list of RFC 6902 JSON Patch operations, not a whole object: `{"op": "replace", "path":
  "/premise", "value": "..."}` sets a plain scalar field that already has a value; a
  `DimensionField` (e.g. `plot.structure`, a character's `role`) is an object, so target its
  `.../value` and `.../settled` sub-paths separately, e.g. `{"op": "replace", "path":
  "/plot/structure/value", "value": "three-act"}`; `{"op": "add", "path": "/characters/-",
  "value": {...}}` appends to a list (same `/-` pattern for other list
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: All pass, including the pre-existing orchestrator-prompt tests (`test_orchestrator_prompt_documents_chapter_writing_loop`, `test_orchestrator_prompt_uses_update_chapter_for_revision_count`, `test_orchestrator_prompt_calls_finalize_story_before_delegating_to_editor`, `test_orchestrator_prompt_never_writes_a_chapter_filename_itself`, `test_orchestrator_prompt_forbids_parallel_chapter_delegation`) -- none of them depend on the exact step numbers you just changed, only on phrase presence/ordering, which this rewrite preserves.

- [ ] **Step 8: Commit**

```bash
git add src/psalm_saga/prompts/orchestrator.md tests/test_prompts.py
git commit -m "docs(prompts): gate chapter-planner-agent on full bible settlement in both modes"
```

---

### Task 6: `brainstorm.md` -- context mining, multi-field proposals, turn-budget three-way choice

**Files:**
- Modify: `src/psalm_saga/prompts/brainstorm.md`
- Modify: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `settlement_override`/`settlement_override_reason` fields (Task 1), `check_bible_readiness` (Task 2, referenced conceptually -- brainstorm-agent itself doesn't call it, the orchestrator does), `max_brainstorm_turns` passed in the delegation task (Task 5).
- Produces: no code interfaces -- this is the last task, closing out the design's brainstorm-agent behavior changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompts.py`:

```python
def test_brainstorm_prompt_mines_initial_context_before_asking() -> None:
    text = load_prompt("brainstorm")
    assert "mine" in text.lower() or "mining" in text.lower()
    # the mining instruction must appear before the "Ground rules" section (i.e. before the
    # general question-asking rules), establishing it as a first-turn step
    assert text.index("initial context") < text.index("## Ground rules")


def test_brainstorm_prompt_promotes_multi_field_proposals() -> None:
    text = load_prompt("brainstorm")
    assert "settle" in text.lower()
    assert "at once" in text.lower() or "in the same" in text.lower()


def test_brainstorm_prompt_turn_budget_offers_three_options() -> None:
    text = load_prompt("brainstorm")
    assert "settlement_override" in text
    assert "keep going" in text.lower() or "raise" in text.lower()
    assert "you decide" in text.lower()


def test_brainstorm_prompt_no_longer_references_old_four_field_minimum() -> None:
    text = load_prompt("brainstorm")
    assert "is_ready_for_writing checks: premise, at least one character" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py -k "mines_initial_context or multi_field or turn_budget_offers or old_four_field" -v`
Expected: FAIL.

- [ ] **Step 3: Add the context-mining first-turn step**

In `src/psalm_saga/prompts/brainstorm.md`, insert a new section right after the `## The core skill: translate dimensions into story talk` section's table and before `## Conversation shape, not dimension order`:

```markdown
## Mining the initial context first

If your task included initial context from the user and this is your first invocation of the
session (the bible has no `premise` yet), spend your first turn on it before your first
`ask_human` call:

1. **Take stated facts as given.** Anything the context states outright -- a character's name, an
   explicit setting, a stated tone or genre -- settle directly via `update_story_bible`
   (`settled: true`), no question asked. Re-asking something the user already told you is exactly
   the annoyance this step exists to avoid.
2. **Confidently interpret what it implies but doesn't state.** A sparse one-line pitch still
   implies more than it says outright -- treat it the way you'd treat having no context at all
   (see the table above): invent a handful of vivid, mutually different, specific proposals
   *grounded in that context* rather than generic ones, and lead your first `ask_human` call with
   the strongest one.

Both passes apply the same way whether the context is a single sentence or a detailed paragraph --
a detailed context just yields more directly-settled material in pass 1, leaving less for pass 2
and the question loop that follows.
```

- [ ] **Step 4: Promote the multi-field-proposal guidance**

In the `## Ground rules` section, replace the bullet:
```markdown
- Before each turn, use `think` to decide: given everything settled so far, what's the most
  interesting, specific thing to propose or ask next -- and how would *this* story's own details
  make that proposal concrete rather than generic. Skip anything the user has clearly already
  answered or handed to your judgment.
```
with:
```markdown
- Before each turn, use `think` to decide: given everything settled so far, what's the most
  interesting, specific thing to propose or ask next -- and how would *this* story's own details
  make that proposal concrete rather than generic. Skip anything the user has clearly already
  answered or handed to your judgment. As part of that same `think` step, check which *other*
  still-unsettled fields this proposal could plausibly settle at once (a good antagonist proposal
  can settle a character, a plot turning point, and a world-rule together) -- shape the question to
  ask for all of them as one coherent creative choice, then apply every field it resolves in the
  same `update_story_bible` call once the user answers, rather than looping back through each field
  separately. This is how you minimize the number of questions without bundling unrelated questions
  into one `ask_human` call -- each call still asks about one coherent creative choice, that choice
  just gets to be a bigger one.
```

- [ ] **Step 5: Replace the turn-budget guidance**

Replace this existing bullet in `## Ground rules`:
```markdown
- Respect the configured turn budget (given in your task). If you're approaching it, prioritize
  getting the *required* fields (see `is_ready_for_writing` checks: premise, at least one
  character, plot.structure, plot.inciting_incident) settled over polishing optional ones -- but
  even a "just get it settled" question should still be a concrete proposal, not a bare label.
```
with a new standalone section (place it right before `## If invoked to resolve originality-guard findings (from_scratch mode)`):

```markdown
## When you're approaching your turn budget

Your task tells you your `max_brainstorm_turns` for this invocation. Track how many `ask_human`
calls you've made so far. When you're about to exceed the budget and the bible still isn't fully
settled, don't ask another domain question -- ask exactly one meta-question instead, with exactly
these three options (via `ask_human`, `options` set), each with its consequence stated in `why` so
the user can choose with full information:

- **"Keep going a while longer"** -- raises your effective budget by 20 turns. Consequence: more
  questions, more time, but a fuller bible.
- **"You decide the rest"** -- you settle every remaining unsettled field yourself (see "If the
  user says 'you decide'" above), specific and considered, consistent with everything already
  established, noting every assumption in your final report. Consequence: no more questions, but
  some choices will be yours rather than the user's.
- **"Generate from here as-is"** -- set `settlement_override: true` via `update_story_bible`, plus
  a short `settlement_override_reason` summarizing what's being left unsettled. Consequence: the
  story may be inconsistent or generic on whatever's left unsettled, since downstream steps will
  improvise those parts.

Whichever the user picks, act on it immediately and don't ask this meta-question again unless you
hit the new (raised) budget too.
```

- [ ] **Step 6: Update the remaining "ready for writing" references**

Replace, at the top of the file:
```markdown
call. The one exception is your genuine final message
once the bible is ready for writing (or the divergence plan is confirmed) -- see "When you're
done" at the end of this file; that is the only turn allowed to end without a tool call.
```
with:
```markdown
call. The one exception is your genuine final message
once the bible is fully settled (or `settlement_override` was explicitly set -- see "When you're
approaching your turn budget" below) or the divergence plan is confirmed -- see "When you're
done" at the end of this file; that is the only turn allowed to end without a tool call.
```

And at the very end of the file, replace:
```markdown
When you're done (bible ready for writing, or divergence plan confirmed/complete), say so plainly
in your final message instead of continuing to ask questions.
```
with:
```markdown
When you're done (bible fully settled, `settlement_override` explicitly set, or divergence plan
confirmed/complete), say so plainly in your final message instead of continuing to ask questions.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: All pass, including the pre-existing brainstorm-prompt tests (`test_brainstorm_prompt_documents_json_patch_ops`, `test_brainstorm_prompt_requires_title_proposal_not_optional`).

- [ ] **Step 8: Run the full suite one final time**

Run: `pytest tests/ -v`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add src/psalm_saga/prompts/brainstorm.md tests/test_prompts.py
git commit -m "docs(prompts): mine initial context first, promote multi-field proposals, add turn-budget three-way choice"
```

---

### Task 7: `extractor.md` -- mark confident extractions settled, fix stale patch-shape examples

**Files:**
- Modify: `src/psalm_saga/prompts/extractor.md`
- Modify: `tests/test_prompts.py`

**Interfaces:**
- Consumes: the design decision from the spec's "Extraction settling" section -- a confident
  extraction counts as settled on its own, no separate brainstorm-agent confirmation needed
  (Task 5's from_source sequence in `orchestrator.md` only sends `brainstorm-agent` to settle
  whatever `extractor-agent` left `settled: false`, so this task is what makes that distinction
  meaningful instead of every field starting `settled: false` regardless of confidence).
- Produces: no code interfaces -- prompt content only.

Without this task, `extractor-agent` has no instruction telling it to ever set `settled: true` --
today's `extractor.md` only ever mentions the negative case ("leave ... `settled: false`"), so left
alone, every extracted field would stay unsettled regardless of how clearly the source supported
it, and the from_source sequence built in Task 5 would always need a full brainstorm settle-pass
even for a source text that answered everything unambiguously.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompts.py`:

```python
def test_extractor_prompt_marks_confident_extractions_settled() -> None:
    text = load_prompt("extractor")
    assert "settled: true" in text or "settled\": true" in text or "settled=True" in text


def test_extractor_prompt_patch_examples_use_dimension_field_shape() -> None:
    text = load_prompt("extractor")
    # the old bare-value example must be gone -- /plot/structure is a DimensionField now
    assert '"/plot/structure", "value": "three-act"' not in text
    assert "/plot/structure/value" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompts.py -k "marks_confident_extractions_settled or dimension_field_shape" -v`
Expected: FAIL.

- [ ] **Step 3: Add the "mark it settled" instruction to step 2**

In `src/psalm_saga/prompts/extractor.md`, change:

```markdown
2. For each PSALM dimension, extract what the text actually supports -- do not invent detail the
   source doesn't contain. Where the text is ambiguous or silent on a sub-dimension, leave the
   `DimensionField.value` empty and `settled: false` rather than guessing; the brainstorm subagent
   will resolve genuine gaps with the user later.
```
to:
```markdown
2. For each PSALM dimension, extract what the text actually supports -- do not invent detail the
   source doesn't contain. When the source clearly and unambiguously supports a value, set both
   `DimensionField.value` and `settled: true` together -- a confident extraction stands on its own,
   with no separate confirmation pass needed, so don't leave `settled: false` out of caution once
   you're actually confident. Where the text is ambiguous or silent on a sub-dimension, leave the
   `DimensionField.value` empty and `settled: false` rather than guessing; the orchestrator will
   send `brainstorm-agent` to resolve whatever you leave unsettled with the user later.
```

- [ ] **Step 4: Fix the stale patch-shape examples in step 5**

Change:
```markdown
5. Call `update_story_bible` with what you've extracted, as a list of RFC 6902 JSON Patch
   operations -- `{"op": "replace", "path": "/mode", "value": "from_source"}`,
   `{"op": "replace", "path": "/source_excerpt_path", "value": "..."}`, one `replace` per
   scalar/object field (`/premise`, `/plot/structure`, `/writing_style/tone/value`, etc.), and one
   `{"op": "add", "path": "/characters/-", "value": {...}}` per character (same pattern for
   `scenes`, `themes`, `turning_points`). Never `write_file`/`edit_file` on `story_bible.json`
```
to:
```markdown
5. Call `update_story_bible` with what you've extracted, as a list of RFC 6902 JSON Patch
   operations -- `{"op": "replace", "path": "/mode", "value": "from_source"}`,
   `{"op": "replace", "path": "/source_excerpt_path", "value": "..."}`, one `replace` per plain
   scalar field (`/premise`), and for a `DimensionField` (`/plot/structure`, `/writing_style/tone`,
   etc.) a pair of ops targeting `.../value` and `.../settled` -- e.g. `{"op": "replace", "path":
   "/plot/structure/value", "value": "three-act"}` followed by `{"op": "replace", "path":
   "/plot/structure/settled", "value": true}` once you're confident enough to mark it settled (see
   step 2). One `{"op": "add", "path": "/characters/-", "value": {...}}` per character (same
   pattern for `scenes`, `themes`, `turning_points`) -- a character's own gated fields (`role`,
   `external_goal`, etc.) are `DimensionField` objects too, so their value in that `add` op looks
   like `{"name": "Finn", "role": {"value": "...", "settled": true}, ...}`. Never `write_file`/
   `edit_file` on `story_bible.json`
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: All pass, including the pre-existing `test_extractor_prompt_documents_json_patch_ops`.

- [ ] **Step 6: Run the full suite one final time**

Run: `pytest tests/ -v`
Expected: All pass. This is the last task in the plan -- the full suite passing here confirms the
whole feature (schema, gate tool, both orchestrator sequences, brainstorm-agent's new behavior,
and extractor-agent's settled-marking) is consistent end to end.

- [ ] **Step 7: Commit**

```bash
git add src/psalm_saga/prompts/extractor.md tests/test_prompts.py
git commit -m "docs(prompts): mark confident extractions settled, fix stale DimensionField patch examples"
```
