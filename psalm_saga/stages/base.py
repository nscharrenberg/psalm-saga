"""Stage protocol, registry and the shared run context.

A stage is a small class with `applies`, `done` and `run`. Stages are looked up by
(name, impl) so a preset can swap an implementation — e.g. `draft: {impl: oneshot}`
for the flat baseline or `draft: {impl: agents_room}` — without code changes. Third
parties can register their own with `@register("draft", "my_writer")`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from psalm_saga.config import PipelineConfig, StageConfig
from psalm_saga.llm import LLM, Part
from psalm_saga.prompting import Prompts
from psalm_saga.store import RunStore
from psalm_saga.taxonomy import Taxonomy
from psalm_saga.text.language import language_directive

_REGISTRY: dict[tuple[str, str], type[Stage]] = {}

S = TypeVar("S", bound="type[Stage]")


def register(name: str, impl: str | None = None) -> Callable[[S], S]:
    def deco(cls: S) -> S:
        cls.name = name
        cls.impl = impl or name
        _REGISTRY[(name, cls.impl)] = cls
        return cls

    return deco


def get_stage(name: str, impl: str | None) -> type[Stage]:
    key = (name, impl or name)
    if key not in _REGISTRY:
        options = sorted(i for (n, i) in _REGISTRY if n == name)
        raise ValueError(f"No implementation {key[1]!r} for stage {name!r}. Available: {options}")
    return _REGISTRY[key]


def available() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n, i in _REGISTRY:
        out.setdefault(n, []).append(i)
    return out


@dataclass
class RunContext:
    config: PipelineConfig
    store: RunStore
    llm: LLM
    taxonomy: Taxonomy
    prompts: Prompts
    mode: str  # "source" | "premise" | "spec"
    language: str = "en"
    state: dict[str, Any] = field(default_factory=dict)

    def emit(self, type_: str, **kw) -> None:
        self.store.emit({"type": type_, **kw})

    @property
    def variety(self):
        """The language variety the story prose must use (from spec.json), or None for the standard language."""
        if not self.store.exists("spec.json"):
            return None
        from psalm_saga.artifacts import Spec

        v = self.store.read_json("spec.json", Spec).variety
        return v if v is not None and not v.standard else None

    @property
    def style_targets(self) -> dict | None:
        """Measured rhythm of the source ({"stylometrics", "shape"}), when the policy preserves the
        writing style. Numbers only (profile.json), so the writer stays behind the clean-room boundary."""
        if "style_targets" not in self.state:
            out = None
            pol = (self.config.transform.policy or {}).get("writing_style", "preserve")
            if self.mode == "source" and pol == "preserve" and self.store.exists("profile.json"):
                prof = self.store.read_json("profile.json")
                if prof.get("stylometrics"):
                    out = {"stylometrics": prof["stylometrics"], "shape": prof.get("shape") or {},
                           "form": prof.get("form") or {"form": "prose"}}
            self.state["style_targets"] = out
        return self.state["style_targets"]

    def system(self, role: str) -> str:
        return self.prompts.render("system", role=role, mode=self.mode,
                                   language_directive=language_directive(self.language, self.variety))

    def hints(self, **kw) -> dict:
        # state["variant"] makes every call of a repeated analysis a fresh sample (not a cache hit),
        # e.g. the second extraction of the source used to measure the extractor's own agreement.
        base = {"language": self.language}
        if self.state.get("variant") and "variant" not in kw:
            base["variant"] = self.state["variant"]
        return {**base, **kw}

    # Convenience wrappers so stages read cleanly.
    async def text(self, model_role: str, role_text: str, parts: list[Part], **kw) -> str:
        return await self.llm.text(model_role, self.system(role_text), parts, **kw)

    async def json(self, model_role: str, role_text: str, parts: list[Part], schema, **kw):
        return await self.llm.json(model_role, self.system(role_text), parts, schema, **kw)


@dataclass
class Backtrack:
    """Returned by a stage to send the run back to an earlier stage (e.g. review found that the
    specification itself is at fault). The pipeline invalidates from `to_stage` and continues;
    the number of backtracks per run is bounded by the stage that asks for them."""

    to_stage: str
    reason: str = ""


class Stage:
    name: ClassVar[str] = ""
    impl: ClassVar[str] = ""
    modes: ClassVar[tuple[str, ...]] = ("source", "premise", "spec")
    outputs: ClassVar[tuple[str, ...]] = ()  # glob patterns this stage writes (for resume/invalidate)

    def __init__(self, cfg: StageConfig):
        self.cfg = cfg
        self.params = cfg.params

    @property
    def model_role(self) -> str:
        return self.cfg.model or self.name

    def applies(self, ctx: RunContext) -> bool:
        return ctx.mode in self.modes

    def done(self, ctx: RunContext) -> bool:
        return bool(self.outputs) and all(ctx.store.glob(p) for p in self.outputs)

    def invalidate(self, ctx: RunContext) -> None:
        for p in self.outputs:
            ctx.store.delete(p)

    async def run(self, ctx: RunContext) -> Backtrack | None:  # pragma: no cover - interface
        raise NotImplementedError


async def gather_limited(items: Iterable, fn: Callable[[Any], Awaitable[Any]], limit: int) -> list:
    """Run fn over items with bounded concurrency, preserving order."""
    sem = asyncio.Semaphore(max(1, limit))

    async def one(x):
        async with sem:
            return await fn(x)

    return await asyncio.gather(*(one(x) for x in items))
