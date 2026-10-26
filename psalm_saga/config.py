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
    """One model endpoint. `name` is any LiteLLM model id (provider/model)."""

    name: str = "anthropic/claude-sonnet-5-5"
    temperature: float | None = 0.8
    max_output_tokens: int = 8000
    # Floor under every call's output allowance. Reasoning models spend part of it on hidden
    # reasoning; a tight cap sized to a short poem (a few hundred tokens) then returns nothing.
    min_output_tokens: int = 2048
    # Reasoning models think before they answer, and the thinking counts against the output
    # allowance. For them, `reasoning_headroom` tokens are added on top of what the visible answer
    # needs (the cap rises with it). None = auto: LiteLLM's model table, or reasoning tokens seen in
    # an answer. How much a model reasons is set by the provider's own knob, e.g.
    # extra.reasoning_effort = low | medium | high; the headroom only keeps that from being cut off.
    reasoning: bool | None = None
    reasoning_headroom: int = 8000
    context_window: int = 200_000
    timeout_s: float = 600.0
    max_concurrency: int = 4
    rpm: int | None = None  # requests per minute; None = unlimited
    tpm: int | None = None  # tokens per minute (input+output estimate); None = unlimited
    max_retries: int = 8
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
    max_parallel_chapters: int = 3  # chapters drafted concurrently (uses rolling summaries of the plan, not prior prose)


class JudgesConfig(_Base):
    """Model judges in the evaluation (optional; off by default). Judges are best run on a model of a
    different family from the writer, to avoid self-preference, so the model is set here separately."""

    enabled: bool = False
    model: str | None = None  # LiteLLM model id; None = models.judge if set, else the default model (not advised)
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
    cache: bool = True
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
    items = overrides.items() if isinstance(overrides, dict) else [parse_override(o) for o in overrides or []]
    for key, value in items:
        set_dotted(data, key, value)
    # Models other than "default" inherit unspecified fields from default.
    models = data.get("models") or {}
    default = models.get("default", {})
    for role, m in list(models.items()):
        if role != "default":
            models[role] = _deep_merge(default, m or {})
    return PipelineConfig.model_validate(data)
