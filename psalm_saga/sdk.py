"""Python SDK.

    from psalm_saga import Saga

    saga = Saga("full", overrides={"models.default.name": "openai/gpt-5.5"})
    run = saga.synthesize(open("book.txt").read())        # source -> synthetic counterpart
    print(run.story[:500], run.evaluation["leakage"])

    run.edit("spec", "Make the narrator intrude with ironic asides.")  # re-plans & redrafts on next run()
    run.run()

    draft = saga.write(premise="Een vuurtorenwachter vindt een fles ...")  # premise -> story
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from psalm_saga.artifacts import Bible, ChapterDraft, ChapterPlan, Plan, Spec, TransformMap
from psalm_saga.config import PipelineConfig, load_config
from psalm_saga.llm import Part
from psalm_saga.pipeline import Pipeline
from psalm_saga.store import RunStore

# name -> (file, model, first stage to re-run after an edit)
EDITABLE: dict[str, tuple[str, type[BaseModel] | None, str]] = {
    "spec_source": ("spec_source.json", Spec, "transform"),
    "transform": ("transform.json", TransformMap, "transform"),
    "spec": ("spec.json", Spec, "plan"),
    "bible": ("bible.json", Bible, "plan"),
    "plan": ("plan.json", Plan, "draft"),
}


def _sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Inside a running event loop: use the async variants (await run.arun(), saga.asynthesize()).")


class Run:
    """Handle on one run directory."""

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline

    @property
    def store(self) -> RunStore:
        return self.pipeline.store

    @property
    def id(self) -> str:
        return self.store.id

    @property
    def path(self) -> Path:
        return self.store.root

    # -------------------------------------------------------------- artifacts

    def artifact(self, name: str) -> Any:
        if name.startswith("chapter:"):
            return self.store.maybe(f"chapters/ch_{int(name.split(':')[1]):03d}.json", ChapterDraft)
        if name in EDITABLE:
            file, model, _ = EDITABLE[name]
            return self.store.maybe(file, model) if model else None
        for f in (f"{name}.json", f"{name}.md", name):
            if self.store.exists(f):
                return self.store.read_json(f) if f.endswith(".json") else self.store.read_text(f)
        return None

    @property
    def story(self) -> str:
        return self.store.read_text("story.md") if self.store.exists("story.md") else ""

    @property
    def spec(self) -> Spec | None:
        return self.store.maybe("spec.json", Spec)

    @property
    def plan(self) -> Plan | None:
        return self.store.maybe("plan.json", Plan)

    @property
    def bible(self) -> Bible | None:
        return self.store.maybe("bible.json", Bible)

    @property
    def evaluation(self) -> dict:
        return self.store.read_json("evaluation.json") if self.store.exists("evaluation.json") else {}

    def status(self) -> dict:
        return self.pipeline.status()

    def export(self, path: str | Path | None = None, *, release: bool = False) -> Path:
        """Zip the run: full (incl. source, internal use) or release (synthetic material only)."""
        from psalm_saga.bundle import build_bundle

        out = Path(path or self.path.parent / f"{self.id}-{'release' if release else 'full'}.zip")
        out.write_bytes(build_bundle(self.path, release=release))
        return out

    def graph(self, which: str = "synthetic", against: str = "design") -> dict:
        """The story knowledge graph (see psalm_saga.graph).

        which = "synthetic" (the design the story was written from), "source", "recovered"
        (re-extracted from the synthetic text; see `recover`) or "compare": the source graph
        aligned with the synthetic one (`against` = "design" or "text"; "calibration" aligns it with a
        second analysis of the source itself, which shows the analysis noise), every node and edge
        marked kept / changed / source_only / synthetic_only."""
        from psalm_saga.graph import build_graph, compare_graphs, counterpart_map

        if which == "compare":
            tmap = self.store.maybe("transform.json", TransformMap)
            if against == "calibration":
                # the source analysed a second time: every difference here is analysis noise
                cal = self.path / "calibration" / "bible_source.json"
                if not cal.exists():
                    raise FileNotFoundError("No second analysis of the source yet (stage recover, calibrate=true)")
                return compare_graphs(self.graph("source"), build_graph(Bible.model_validate_json(cal.read_text(encoding="utf-8"))), {})
            if against == "text":
                rec = self.recovered_bible()
                if rec is None:
                    raise FileNotFoundError("The synthetic text has not been re-extracted yet (run.recover())")
                other = build_graph(rec)
                out = compare_graphs(self.graph("source"), other, (tmap.as_dict() if tmap else {}))
                cal = self.path / "calibration" / "bible_source.json"
                if cal.exists():  # the noise floor: how far the source agrees with its own second analysis
                    out["ceiling"] = compare_graphs(self.graph("source"), build_graph(
                        Bible.model_validate_json(cal.read_text(encoding="utf-8"))), {})["summary"]
                return out
            else:
                other = self.graph("synthetic")
            return compare_graphs(self.graph("source"), other, (tmap.as_dict() if tmap else {}))
        if which == "recovered":
            rec = self.recovered_bible()
            if rec is None:
                raise FileNotFoundError("The synthetic text has not been re-extracted yet (run.recover())")
            return build_graph(rec)
        name = "bible_source.json" if which == "source" else "bible.json"
        bible = self.store.maybe(name, Bible) or (self.store.maybe("bible_source.json", Bible) if which != "source" else None)
        if bible is None:
            raise FileNotFoundError(f"No story bible for {which!r} in this run yet")
        return build_graph(bible, counterpart=counterpart_map(self.store.maybe("transform.json", TransformMap), which))

    def recovered_bible(self) -> Bible | None:
        p = self.path / "recovered" / "bible_source.json"
        return Bible.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    async def arecover(self) -> Bible:
        """Extract a story bible from the synthetic text with the same extractor used on the
        source (stage `recover`, into `recovered/`), then refresh the evaluation."""
        if (rec := self.recovered_bible()) is not None:
            return rec
        if not self.story:
            raise FileNotFoundError("No synthetic story yet")
        from psalm_saga.config import StageConfig

        stages = self.pipeline.config.stages
        if "recover" not in stages or not stages["recover"].enabled:
            stages["recover"] = StageConfig()
        await self.pipeline.run(only=["recover", "evaluate"])
        rec = self.recovered_bible()
        if rec is None:
            raise RuntimeError("Re-extraction produced no story bible")
        return rec

    def recover(self) -> Bible:
        return _sync(self.arecover())

    # -------------------------------------------------------------- execution

    async def arun(self, **kw) -> Run:
        await self.pipeline.run(**kw)
        return self

    def run(self, **kw) -> Run:
        return _sync(self.arun(**kw))

    # -------------------------------------------------------------- editing

    def put(self, name: str, value: Any) -> None:
        """Replace an artifact (hand edit) and invalidate everything downstream of it."""
        if name.startswith("chapter:"):
            idx = int(name.split(":")[1])
            d = self.store.read_json(f"chapters/ch_{idx:03d}.json", ChapterDraft)
            d.text = value if isinstance(value, str) else value["text"]
            d.word_count = len(d.text.split())
            self.store.write_json(f"chapters/ch_{idx:03d}.json", d)
            self._invalidate("assemble")
            return
        if name.startswith("chapter_plan:"):
            idx = int(name.split(":")[1])
            plan = self.store.read_json("plan.json", Plan)
            cp = value if isinstance(value, ChapterPlan) else ChapterPlan.model_validate(value)
            plan.chapters = [cp if c.index == idx else c for c in plan.chapters]
            self.store.write_json("plan.json", plan)
            self.store.write_json(f"plan/ch_{idx:03d}.json", cp)
            self.store.delete(f"chapters/ch_{idx:03d}.json")
            self.store.delete(f"reviews/ch_{idx:03d}.json")
            self._invalidate("guard")
            return
        file, model, rerun = EDITABLE[name]
        obj = value if isinstance(value, BaseModel) else model.model_validate(value)  # type: ignore[union-attr]
        self.store.write_json(file, obj)
        if name == "transform":  # keep the edited names; regenerate what depends on them
            self.store.delete("spec.json")
            self.store.delete("bible.json")
            rerun = "plan"
        self._invalidate(rerun)

    def _invalidate(self, stage: str) -> None:
        names = [s.name for s in self.pipeline.stages()]
        while stage not in names and stage != "evaluate":
            order = ["transform", "plan", "draft", "review", "guard", "assemble", "evaluate"]
            stage = order[order.index(stage) + 1] if stage in order else "evaluate"
        if stage in names:
            self.pipeline.invalidate_from(stage)

    async def aedit(self, name: str, instruction: str) -> Any:
        """Apply a natural-language instruction to an artifact with the model."""
        ctx = self.pipeline.context()
        role = "You are the story's editor. Apply the instruction precisely and keep everything else unchanged."
        if name.startswith("chapter:"):
            d = self.artifact(name)
            text = await ctx.text("review", role, [Part(ctx.prompts.render("edit", instruction=instruction, artifact=d.text))],
                                  hints=ctx.hints(target_words=d.word_count), tag=f"edit:{name}")
            from psalm_saga.stages.draft import clean_prose

            self.put(name, clean_prose(text))
            return self.artifact(name)
        if name.startswith("chapter_plan:"):
            idx = int(name.split(":")[1])
            plan = self.store.read_json("plan.json", Plan)
            cur = next(c for c in plan.chapters if c.index == idx)
            new = await ctx.json("plan", role, [Part(ctx.prompts.render("edit", instruction=instruction,
                                 artifact=cur.model_dump_json(indent=1)))], ChapterPlan, hints=ctx.hints(), tag=f"edit:{name}")
            new.index = idx
            self.put(name, new)
            return new
        file, model, _ = EDITABLE[name]
        cur = self.store.read_json(file, model)
        new = await ctx.json("spec" if name.startswith("spec") else "plan", role,
                             [Part(ctx.prompts.render("edit", instruction=instruction, artifact=cur.model_dump_json(indent=1)))],
                             model, hints=ctx.hints(), tag=f"edit:{name}")
        self.put(name, new)
        return new

    def edit(self, name: str, instruction: str) -> Any:
        return _sync(self.aedit(name, instruction))


class Saga:
    """Factory for runs with a fixed configuration."""

    def __init__(self, preset: str | dict | PipelineConfig = "full", *, overrides: list[str] | dict | None = None,
                 runs_dir: str | Path = "runs", on_event: Callable[[dict], None] | None = None):
        self.config = load_config(preset, overrides)
        self.runs_dir = Path(runs_dir)
        self.on_event = on_event

    def create(self, *, source: str | None = None, premise: str | None = None, spec: Spec | dict | None = None,
               run_id: str | None = None, meta: dict | None = None) -> Run:
        return Run(Pipeline.create(self.config, source=source, premise=premise, spec=spec, runs_dir=self.runs_dir,
                                   run_id=run_id, on_event=self.on_event, meta=meta))

    async def asynthesize(self, source: str, **kw) -> Run:
        return await self.create(source=source, **kw).arun()

    def synthesize(self, source: str, **kw) -> Run:
        return _sync(self.asynthesize(source, **kw))

    async def awrite(self, *, premise: str | None = None, spec: Spec | dict | None = None, **kw) -> Run:
        return await self.create(premise=premise, spec=spec, **kw).arun()

    def write(self, *, premise: str | None = None, spec: Spec | dict | None = None, **kw) -> Run:
        return _sync(self.awrite(premise=premise, spec=spec, **kw))

    @staticmethod
    def open(run_dir: str | Path, overrides: list[str] | dict | None = None,
             on_event: Callable[[dict], None] | None = None) -> Run:
        return Run(Pipeline.open(run_dir, overrides=overrides, on_event=on_event))

    @staticmethod
    def list_runs(runs_dir: str | Path = "runs") -> list[dict]:
        out = []
        for p in sorted(Path(runs_dir).glob("*/run.json")):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({k: m.get(k) for k in ("id", "preset", "status", "mode", "language", "created", "finished", "error",
                                              "parent", "root", "version", "fixes", "fix_titles")}
                       | {"cost_usd": (m.get("usage") or {}).get("cost_usd", 0), "path": str(p.parent)})
        return out
