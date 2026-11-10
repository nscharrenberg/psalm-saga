"""Configuration: one pydantic model, loadable from YAML presets with inheritance and
dotted-key overrides, so experiments can toggle or swap any part of the pipeline
without touching code.

    cfg = load_config("full", overrides=["stages.review.enabled=false",
                                         "models.default.name=openai/gpt-5"])
"""

from __future__ import annotations

import copy
import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(_Base):
    """One model endpoint. `name` is any LiteLLM model id (provider/model). `use` names an entry of the
    model library (psalm_saga/model_library.py): its settings are copied in, so a model is described once
    and chosen by name for every task; `temperature` stays with the task."""

    use: str | None = None

    name: str = "anthropic/claude-sonnet-5-5"
    temperature: float | None = 0.8
    max_output_tokens: int = 8000
    # Floor under every call's output allowance. Reasoning models spend part of it on hidden
    # reasoning; a tight cap sized to a short poem (a few hundred tokens) then returns nothing.
    min_output_tokens: int = 2048
    # Reasoning models think before they answer, and the thinking counts against the output
    # allowance. For them, `reasoning_headroom` tokens are added on top of what the visible answer
    # needs (the cap rises with it); it is a fixed ceiling, never raised by what earlier calls used.
    # None = auto: LiteLLM's model table, or reasoning tokens seen in an answer. How much a model
    # reasons is set by the provider's own knob, e.g. extra.reasoning_effort = none | minimal | low |
    # medium | high (none: no headroom is added); the headroom only keeps that from being cut off.
    # OpenRouter's provider routing goes in extra too: provider_order ("a, b"), provider_sort
    # (price | throughput | latency), provider_fallbacks (bool), or OpenRouter's own extra.provider object.
    reasoning: bool | None = None
    reasoning_headroom: int = 8000
    # Upper limit on a reasoning model's hidden reasoning per call, where the provider takes one (OpenRouter,
    # Anthropic); None = the provider's default for the reasoning effort. Keeps a model from spending minutes
    # and the whole allowance thinking about a small task.
    reasoning_max_tokens: int | None = None
    context_window: int = 200_000
    timeout_s: float = 600.0
    max_concurrency: int = 4
    rpm: int | None = None  # requests per minute; None = unlimited
    tpm: int | None = None  # tokens per minute (input+output estimate); None = unlimited
    max_retries: int = 8
    timeout_retries: int = 2  # a call that ran into timeout_s is retried at most this often (the same request tends to time out again)
    stream: bool = True  # stream long generations to avoid idle-connection timeouts
    prompt_cache: bool = True  # mark the stable context prefix cacheable (Anthropic); others cache automatically
    extra: dict[str, Any] = Field(default_factory=dict)  # passed through to litellm (api_base, reasoning_effort, ...)
    # Prices in USD per million tokens. Set these for self-hosted or unlisted models (or to pin the
    # prices used in a paper); when unset, LiteLLM's price table is used.
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    cached_input_cost_per_mtok: float | None = None  # defaults to the input price


class StageConfig(_Base):
    enabled: bool = True
    impl: str | None = None  # registry name; defaults to the stage name
    model: str | None = None  # model role to use; defaults to the stage name, then "default"
    params: dict[str, Any] = Field(default_factory=dict)


DimensionPolicy = Literal["preserve", "abstract", "regenerate"]


class TransformConfig(_Base):
    """How each dimension of a source is carried into the synthetic story.

    preserve   – keep the source's value (paraphrased into a spec, never copied)
    abstract   – keep its function/structure, re-invent the concrete realisation
    regenerate – invent a new value, consistent with everything that is kept
    """

    policy: dict[str, DimensionPolicy] = Field(
        default_factory=lambda: {
            "writing_style": "preserve",
            "narrative_voice": "preserve",
            "character": "abstract",
            "plot_structure": "preserve",
            "scene_sequence": "abstract",
            "world_building": "abstract",
        }
    )
    rename_entities: bool = True  # consistent fresh names for every named entity
    keep_cultural_setting: bool = True  # new names/places fit the source's culture and period
    # Real places, nations, seas, historical events and public legends (the Pacific, Finland, the
    # Flying Dutchman) are part of the shared world, not the author's expression. None = keep them
    # when world building is preserved; True / False forces it.
    keep_real_names: bool | None = None
    notes: str = ""  # free-text instruction appended to the transform prompt


class LengthConfig(_Base):
    target_words: int | None = None  # None = match the source (source mode) or 3000 (premise mode)
    tolerance: float = 0.15
    chapters: int | Literal["auto", "match"] = "match"  # match = same count as source when available
    max_chapter_words: int = 6000  # longer chapters are split into scene-sized calls


class LanguageConfig(_Base):
    output: str = "auto"  # "auto" = same as input; else ISO 639-1 code ("nl", "de", ...)
    enforce: bool = True  # detect the language of every generated chapter and retry on mismatch
    max_retries: int = 2
    # Language variety of the story prose (dialect, historical spelling, sociolect):
    #   "auto"   keep the source's variety (detected and verified against the source text);
    #            dropped only when the writing-style policy is `regenerate`
    #   "modern" always write contemporary standard language (a modernised corpus)
    #   <text>   a variety you describe, e.g. "19th-century Dutch spelling" or "Scots in the dialogue"
    variety: str = "auto"


class LimitsConfig(_Base):
    max_cost_usd: float | None = None  # abort the run when exceeded
    max_minutes: float | None = None  # stop the run (resumable, nothing lost) after this much working time
    max_parallel_chapters: int = 3  # chapters drafted concurrently (uses rolling summaries of the plan, not prior prose)


class JudgesConfig(_Base):
    """Model judges in the evaluation (optional; off by default). Judges are best run on a model of a
    different family from the writer, to avoid self-preference, so the model is set here separately."""

    enabled: bool = False
    model: str | None = None  # LiteLLM model id; None = models.judge if set, else the default model (not advised)
    # Further judges (a panel): each runs the same instruments; the primary judge (`model`) still decides the
    # grades, the panel adds per-judge results and their agreement. Entries: a model id, or
    # {name: <id>, api_base: <url>, ...} for a self-hosted model (keys other than name go to litellm).
    panel: list[str | dict] = Field(default_factory=list)
    instruments: list[str] = Field(default_factory=lambda: ["psalm", "content", "style"])
    full_text_words: int = 6000  # PSALM reads both texts in full up to this many words each, else aligned excerpts
    excerpt_words: int = 700
    excerpts: int = 3


class PipelineConfig(_Base):
    name: str = "custom"
    description: str = ""
    extends: str | None = None
    taxonomy: str = "psalm"  # built-in name or path to a taxonomy YAML
    prompts_dir: str | None = None  # directory whose *.md templates override the built-in prompts
    stages: dict[str, StageConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=lambda: {"default": ModelConfig()})
    transform: TransformConfig = Field(default_factory=TransformConfig)
    length: LengthConfig = Field(default_factory=LengthConfig)
    language: LanguageConfig = Field(default_factory=LanguageConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    judges: JudgesConfig = Field(default_factory=JudgesConfig)
    # Evaluation measures (keys) or measure groups (form, style, structure, characters, content,
    # distance) the generation should favour; empty = all equally. See psalm_saga/priorities.py.
    priorities: list[str] = Field(default_factory=list)
    # The writing stages (plan, draft, review) see the story graph of the design: characters, places and
    # objects with their relations, events and causal links per chapter. False (ablation `no_graph`): they
    # see only the specification, one synopsis per chapter and the measured scene shapes; the graph is still
    # built, so the evaluation can measure what of it the text realises.
    use_graph: bool = True
    # Check the settings before running (psalm_saga/preflight.py); `preflight_live` adds one tiny
    # test call per model.
    preflight: bool = True
    preflight_live: bool = True
    cache: bool = True
    # Which answers a run may replay from the on-disk response cache. "run" (default): only its own
    # (resuming or redoing a stage is free, but a new run of the same text gets fresh samples);
    # "shared": any run's answer to an identical request (cheap deterministic reruns, e.g. tests).
    cache_scope: str = "run"
    seed: int | None = None
    # Keep every model call in full (messages in, answer and any reasoning out) under calls/, so a
    # run can be traced step by step in the activity view. Left out of release bundles.
    log_calls: bool = True

    def stage(self, name: str) -> StageConfig:
        return self.stages.get(name) or StageConfig(enabled=False)

    def model_for(self, role: str | None) -> ModelConfig:
        if role and role in self.models:
            return self.models[role]
        return self.models["default"]

    def judge_model(self) -> ModelConfig:
        """The primary judge: `judges.model` (a library name or a LiteLLM id), else the `judge` role, else
        the default model. Judges run at temperature 0."""
        from psalm_saga import model_library as ml

        j = self.judges.model
        if j and "judge" in self.models and self.models["judge"].use == j:
            return self.models["judge"].model_copy(update={"temperature": 0.0})
        base = self.models.get("judge") or self.models["default"]
        if j:
            return ml.resolve(j, base, temperature=0.0)
        return base

    def panel_models(self) -> list[ModelConfig]:
        """The further judges of `judges.panel`, in order."""
        from psalm_saga import model_library as ml

        return [ml.resolve(e, self.judge_model(), temperature=0.0) for e in self.judges.panel]

    def fingerprint(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- loading


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def preset_names() -> list[str]:
    root = resources.files("psalm_saga") / "presets"
    return sorted(p.name.removesuffix(".yaml") for p in root.iterdir() if p.name.endswith(".yaml"))


def _read_preset(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    res = resources.files("psalm_saga") / "presets" / f"{name_or_path}.yaml"
    if not res.is_file():
        raise ValueError(f"Unknown preset {name_or_path!r}. Built-in presets: {', '.join(preset_names())}")
    return yaml.safe_load(res.read_text(encoding="utf-8")) or {}


def _resolve(raw: dict, seen: tuple[str, ...] = ()) -> dict:
    parent = raw.get("extends")
    if not parent:
        return raw
    if parent in seen:
        raise ValueError(f"Preset inheritance cycle: {' -> '.join((*seen, parent))}")
    return _deep_merge(_resolve(_read_preset(parent), (*seen, parent)), raw)


def set_dotted(data: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
        if not isinstance(cur, dict):
            raise ValueError(f"Cannot set {key!r}: {part!r} is not a mapping")
    cur[parts[-1]] = value


def parse_override(expr: str) -> tuple[str, Any]:
    if "=" not in expr:
        raise ValueError(f"Override must be key=value, got {expr!r}")
    key, raw = expr.split("=", 1)
    return key.strip(), yaml.safe_load(raw) if raw.strip() else ""


def load_config(
    preset: str | dict | PipelineConfig = "full",
    overrides: list[str] | dict[str, Any] | None = None,
) -> PipelineConfig:
    if isinstance(preset, PipelineConfig):
        data = preset.model_dump(mode="json")
    elif isinstance(preset, dict):
        data = _resolve(copy.deepcopy(preset))
    else:
        data = _resolve(_read_preset(preset))
    # Start from the complete defaults so a partial override (e.g. one transform policy) keeps the rest.
    data = _deep_merge(PipelineConfig().model_dump(mode="json", exclude={"stages"}), data)
    items = list(overrides.items() if isinstance(overrides, dict) else [parse_override(o) for o in overrides or []])
    for key, value in items:
        set_dotted(data, key, value)
    _expand_models(data, items)
    return PipelineConfig.model_validate(data)


def _expand_models(data: dict, items: list[tuple[str, Any]]) -> None:
    """Copy model-library entries into the configuration (see psalm_saga/model_library.py), then let
    roles other than "default" inherit what they do not set from default. An entry is copied when it is
    chosen in this call (an override) or not copied yet; a copy already in a run's settings is kept, so
    the run keeps the model settings it was made with."""
    from psalm_saga import model_library as ml

    chosen = {k.split(".")[1] for k, _ in items if k.startswith("models.") and k.endswith(".use")}
    chosen |= {k.split(".")[1] for k, _ in items if k.startswith("models.") and k.count(".") == 1}
    judges_chosen = any(k in ("judges.model", "judges.panel", "judges") for k, _ in items)

    def fill(role: str, m: dict) -> dict:
        alias = m.get("use")
        if not alias:
            return m
        e = ml.get(alias)
        if e is None:
            raise ValueError(f"models.{role}: no model called {alias!r} in the model library "
                             f"({', '.join(sorted(ml.library()))})")
        if role in chosen or m.get("name") != e.get("name"):
            return {**m, **ml.model_fields(e), "use": alias}
        return m

    models = data.setdefault("models", {})
    own_model = set()
    for role, m in list(models.items()):
        m = dict(m or {})
        if role != "default" and (m.get("name") or m.get("use")):
            own_model.add(role)
            m.setdefault("use", None)  # a model of its own, not the default's library entry
        models[role] = fill(role, m)
    default = models.get("default", {})
    for role, m in list(models.items()):
        if role != "default":
            merged = _deep_merge(default, m or {})
            if role in own_model:  # another model: the default's endpoint and provider options do not apply
                merged["extra"] = dict((m or {}).get("extra") or {})
            models[role] = merged
    j = data.get("judges") or {}
    jm = j.get("model")
    if isinstance(jm, str) and ml.get(jm):
        cur = models.get("judge") or {}
        if judges_chosen or cur.get("use") != jm or cur.get("name") != ml.get(jm).get("name"):
            models["judge"] = {**_deep_merge(default, {}), **ml.model_fields(ml.get(jm)), "use": jm, "temperature": 0.0}
    panel = []
    for entry in j.get("panel") or []:
        if isinstance(entry, str) and ml.get(entry):
            panel.append(ml.expand(entry))
        elif isinstance(entry, dict) and entry.get("use") and ml.get(entry["use"]) and (
                judges_chosen or entry.get("name") != ml.get(entry["use"]).get("name")):
            panel.append(ml.expand({"use": entry["use"]}))
        else:
            panel.append(entry)
    if j.get("panel"):
        j["panel"] = panel
