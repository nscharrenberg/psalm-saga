"""The pipeline engine: an ordered list of configurable stages over a run directory.

Every stage's output is a file, so a run can be resumed after a crash or a rate-limit
storm (finished stages, chunks and chapters are skipped), inspected, hand-edited, and
re-run from any stage (`rerun_from="plan"` invalidates plan and everything after it).
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from psalm_saga.artifacts import Spec
from psalm_saga.config import PipelineConfig, StageConfig, load_config
from psalm_saga.llm import LLM, BudgetExceeded
from psalm_saga.prompting import Prompts
from psalm_saga.stages import get_stage
from psalm_saga.stages.base import Backtrack, RunContext, Stage
from psalm_saga.store import RunStore
from psalm_saga.taxonomy import load_taxonomy
from psalm_saga.text.language import detect_language


class RunStopped(RuntimeError):
    """A stop was requested (run control): the run ends cleanly; finished work is kept and the run
    can be resumed later."""

STAGE_ORDER = ["extract", "spec", "transform", "plan", "draft", "conform", "review", "guard", "assemble", "recover", "evaluate"]
DEFAULT_IMPL = {"draft": "chapter"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id(prefix: str = "") -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix + '-' if prefix else ''}{stamp}-{uuid.uuid4().hex[:6]}"


class Pipeline:
    def __init__(self, store: RunStore, config: PipelineConfig, *, cache_dir: Path | None = None,
                 on_event: Callable[[dict], None] | None = None):
        self.store = store
        self.config = config
        if on_event:
            store.listeners.append(on_event)
        cache = cache_dir if cache_dir is not None else store.root.parent / ".llm_cache"
        self.llm = LLM(config, cache_dir=cache, on_event=store.emit,
                       call_log=(lambda cid, rec: store.write_json(f"calls/{cid}.json", rec)) if config.log_calls else None)
        self.llm.gate = self._gate
        self.llm.load_behaviour(store.meta().get("model_behaviour"))  # what earlier invocations learnt about the models
        if config.cache_scope != "shared":
            # a version of a run (<run>-vN) keeps its parent's answers for the stages it does not redo
            # (those are files already) and samples afresh for the ones it redoes
            self.llm.cache_salt = store.id + (f"#{store.meta().get('redo')}" if store.meta().get("redo") else "")
        self._paused_total = 0.0
        self.taxonomy = load_taxonomy(config.taxonomy)
        self.prompts = Prompts(config.prompts_dir)

    # ------------------------------------------------------------------ construction

    @classmethod
    def create(
        cls,
        config: PipelineConfig | str = "full",
        *,
        source: str | None = None,
        premise: str | None = None,
        spec: Spec | dict | None = None,
        runs_dir: str | Path = "runs",
        run_id: str | None = None,
        overrides: list[str] | dict | None = None,
        on_event: Callable[[dict], None] | None = None,
        meta: dict | None = None,
    ) -> Pipeline:
        cfg = load_config(config, overrides) if isinstance(config, str) or overrides else config
        if sum(x is not None for x in (source, premise, spec)) == 0:
            raise ValueError("Provide a source text, a premise, or a spec.")
        store = RunStore(Path(runs_dir) / (run_id or new_run_id(cfg.name)))
        if source is not None:
            store.write_text("input/source.txt", source)
        if premise is not None:
            store.write_text("input/premise.md", premise)
        if spec is not None:
            store.write_json("input/spec.json", spec if isinstance(spec, dict) else spec.model_dump(mode="json"))
        store.update_meta(id=store.id, created=_now(), status="created", config=cfg.model_dump(mode="json"),
                          preset=cfg.name, usage={}, **(meta or {}))
        return cls(store, cfg, on_event=on_event)

    @classmethod
    def open(cls, run_dir: str | Path, *, overrides: list[str] | dict | None = None,
             on_event: Callable[[dict], None] | None = None) -> Pipeline:
        store = RunStore(run_dir)
        meta = store.meta()
        if not meta:
            raise FileNotFoundError(f"No run at {run_dir}")
        cfg = load_config(PipelineConfig.model_validate(meta["config"]), overrides)
        if overrides:
            store.update_meta(config=cfg.model_dump(mode="json"))
        return cls(store, cfg, on_event=on_event)

    # ------------------------------------------------------------------ settings drift

    def missing_stages(self) -> list[str]:
        """Stages the run's preset has now but this run's saved configuration lacks (a run keeps
        the settings it was created with, so later improvements do not apply to it by themselves)."""
        try:
            current = load_config(self.config.name)
        except Exception:
            return []
        return [n for n in STAGE_ORDER if n in current.stages and current.stages[n].enabled and n not in self.config.stages]

    def adopt_missing_stages(self) -> list[str]:
        """Add the missing stages with the preset's current settings and invalidate from the first."""
        missing = self.missing_stages()
        if not missing:
            return []
        current = load_config(self.config.name)
        for n in missing:
            self.config.stages[n] = current.stages[n]
        self.store.update_meta(config=self.config.model_dump(mode="json"))
        first = min(missing, key=STAGE_ORDER.index)
        names = [s.name for s in self.stages()]
        if first in names:
            self.invalidate_from(first)
        return missing

    # ------------------------------------------------------------------ introspection

    @property
    def mode(self) -> str:
        if self.store.exists("input/source.txt"):
            return "source"
        if self.store.exists("input/spec.json"):
            return "spec"
        return "premise"

    def language(self) -> str:
        want = self.config.language.output
        if want and want != "auto":
            return want
        if self.store.exists("input/source.txt"):
            return detect_language(self.store.read_text("input/source.txt")).code
        if self.store.exists("input/spec.json"):
            lang = json.loads(self.store.read_text("input/spec.json")).get("language")
            if lang:
                return lang
        if self.store.exists("input/premise.md"):
            text = self.store.read_text("input/premise.md")
            det = detect_language(text)
            if det.confidence >= 0.25 and len(text.split()) >= 8:
                return det.code
        return "en"

    def stages(self) -> list[Stage]:
        names = [n for n in STAGE_ORDER if n in self.config.stages] + [n for n in self.config.stages if n not in STAGE_ORDER]
        out = []
        for name in names:
            sc: StageConfig = self.config.stages[name]
            if not sc.enabled:
                continue
            cls = get_stage(name, sc.impl or DEFAULT_IMPL.get(name))
            out.append(cls(_steered(self.config, name, sc)))
        return out

    def context(self) -> RunContext:
        return RunContext(config=self.config, store=self.store, llm=self.llm, taxonomy=self.taxonomy,
                          prompts=self.prompts, mode=self.mode, language=self.language())

    def status(self) -> dict:
        ctx = self.context()
        return {"run": self.store.id, "mode": ctx.mode, "language": ctx.language,
                "stages": [{"name": s.name, "impl": s.impl, "applies": s.applies(ctx), "done": s.applies(ctx) and s.done(ctx)}
                           for s in self.stages()],
                **{k: v for k, v in self.store.meta().items() if k in ("status", "error", "usage", "timing", "current_stage")}}

    def invalidate_from(self, stage_name: str) -> None:
        ctx = self.context()
        stages = self.stages()
        names = [s.name for s in stages]
        if stage_name not in names:
            raise ValueError(f"Stage {stage_name!r} is not enabled in this run ({names})")
        for s in stages[names.index(stage_name):]:
            s.invalidate(ctx)
        ctx.emit("invalidated", from_stage=stage_name)

    # ------------------------------------------------------------------ execution

    async def run(self, *, rerun_from: str | None = None, until: str | None = None, only: list[str] | None = None) -> dict:
        """Run the enabled stages that are not done yet.

        Accounting in run.json accumulates across invocations (resumes, reruns, failures):
          usage   tokens / cost / model-seconds, in total, `by_stage` and `by_tag`
          timing  wall_seconds (total), invocations, and per stage: wall_seconds (all attempts),
                  last_wall_seconds (most recent completed attempt), runs, completed
        """
        if rerun_from:
            self.invalidate_from(rerun_from)
            if self.config.cache_scope != "shared":
                # a redo asks for new samples; a later plain resume of this redo replays them again
                redo = int(self.store.meta().get("redo") or 0) + 1
                self.store.update_meta(redo=redo)
                self.llm.cache_salt = f"{self.store.id}#{redo}"
        ctx = self.context()
        was_done = self.store.meta().get("status") == "done"
        self.store.set_control(None)  # a new invocation starts unpaused
        if self.config.preflight:
            await self.check(only=only, until=until, raise_on_error=True)
        meta = self.store.update_meta(status="running", started=_now(), error=None, language=ctx.language, mode=ctx.mode)
        self._base_usage = dict(meta.get("usage") or {})
        timing = meta.get("timing") or {"wall_seconds": float(meta.get("seconds") or 0.0), "invocations": 0, "stages": {}}
        timing["invocations"] = timing.get("invocations", 0) + 1
        self._timing, self._t0, self._wall0 = timing, time.monotonic(), float(timing.get("wall_seconds", 0.0))
        self._stage, self._s0 = None, None
        self._paused_total = 0.0
        ctx.emit("run_started", mode=ctx.mode, language=ctx.language, preset=self.config.name)
        try:
            backtrack = True
            while backtrack:  # a stage may send the run back to an earlier stage (bounded by that stage)
                backtrack = await self._pass(ctx, until=until, only=only)
        except BudgetExceeded as exc:
            self._fail("budget_exceeded", exc)
            raise
        except RunStopped as exc:
            self._close_stage(completed=False)
            self.store.set_control(None)
            self._checkpoint(status="stopped", current_stage=None, error=None, stopped=_now())
            ctx.emit("run_stopped", reason=str(exc))
            return self.status()
        except BaseException as exc:
            self._fail("failed", exc)
            raise
        # Running only some stages (e.g. a measurement added later) leaves a finished run finished.
        status = "done" if (not until and not only) or (only and was_done) else "partial"
        self._checkpoint(status=status, finished=_now(), current_stage=None)
        ctx.emit("run_finished", status=status, usage=self.llm.usage.to_dict(),
                 wall_seconds=self._timing["wall_seconds"])
        return self.status()

    async def _pass(self, ctx: RunContext, *, until: str | None, only: list[str] | None) -> bool:
        """One pass over the stages; True if a stage asked to go back."""
        for stage in self.stages():
            if only and stage.name not in only:
                continue
            if not stage.applies(ctx):
                continue
            if stage.done(ctx) and stage.name != "evaluate":
                ctx.emit("stage_skipped", stage=stage.name, reason="already done")
                continue
            await self._between_stages(stage.name)
            self._stage, self._s0 = stage.name, time.monotonic()
            self.llm.usage.current_stage = stage.name
            self._checkpoint(current_stage=stage.name)
            ctx.emit("stage_started", stage=stage.name, impl=stage.impl)
            before = self.llm.usage.to_dict().get("by_stage", {})
            result = await stage.run(ctx)
            secs = self._close_stage(completed=True)
            after = self.llm.usage.to_dict().get("by_stage", {})
            ctx.emit("stage_finished", stage=stage.name, seconds=round(secs, 2),
                     **_stage_delta(before, after, stage.name))
            self._checkpoint()
            if isinstance(result, Backtrack):
                ctx.emit("backtrack", stage=stage.name, to_stage=result.to_stage, reason=result.reason)
                self.invalidate_from(result.to_stage)
                return True
            if until and stage.name == until:
                break
        return False

    # ------------------------------------------------------------------ pre-flight and run control

    def pending_stages(self, *, only: list[str] | None = None, until: str | None = None) -> list[str]:
        """Stages a run invocation would execute now (enabled, applicable, not done)."""
        ctx = self.context()
        out = []
        for s in self.stages():
            if only and s.name not in only:
                continue
            if s.applies(ctx) and (not s.done(ctx) or s.name == "evaluate"):
                out.append(s.name)
            if until and s.name == until:
                break
        return out

    async def check(self, *, only: list[str] | None = None, until: str | None = None, live: bool | None = None,
                    raise_on_error: bool = False) -> dict:
        """Pre-flight check of the settings for the stages still to run (psalm_saga/preflight.py)."""
        from psalm_saga.preflight import PreflightFailed, preflight

        stages = self.pending_stages(only=only, until=until)
        has_input = any(self.store.exists(f) for f in ("input/source.txt", "input/premise.md", "input/spec.json"))
        rep = await preflight(self.config, stages=stages, has_input=has_input,
                              live=self.config.preflight_live if live is None else live)
        rep["stages"] = stages
        self.store.write_json("preflight.json", rep)
        self.store.emit({"type": "preflight", "ok": rep["ok"], "problems": rep["problems"],
                         "models": [{k: m.get(k) for k in ("model", "ok", "seconds")} for m in rep["models"]]})
        if raise_on_error and not rep["ok"]:
            self.store.update_meta(status="needs_attention", current_stage=None,
                                   error="settings need attention: " + "; ".join(
                                       p["message"] for p in rep["problems"] if p["severity"] == "error")[:900])
            raise PreflightFailed(rep)
        return rep

    async def _between_stages(self, next_stage: str) -> None:
        c = self.store.control()
        if c.get("action") == "pause_after_stage":
            self.store.set_control("pause", reason=f"paused before {next_stage}", requested=c.get("requested"))
        elif c.get("action") == "stop_after_stage":
            raise RunStopped(f"stopped before {next_stage}")
        await self._gate()

    async def _gate(self) -> None:
        """Called before every model call and between stages: honours pause and stop requests. A
        pause lets the calls already in flight finish and holds every new one until resumed."""
        lim = self.config.limits.max_minutes
        t0 = getattr(self, "_t0", None)
        if lim and t0 is not None and (time.monotonic() - t0 - self._paused_total) / 60 > lim:
            raise RunStopped(f"time limit of {lim:g} minutes reached (limits.max_minutes); everything done so far is "
                             "kept, and continuing the run picks up where it stopped")
        c = self.store.control()
        act = c.get("action")
        if act in (None, "pause_after_stage", "stop_after_stage"):
            return
        if act == "stop":
            raise RunStopped(c.get("reason") or "stopped by the user")
        if act != "pause":
            return
        lock = self.__dict__.setdefault("_pause_lock", asyncio.Lock())
        async with lock:  # one waiter does the bookkeeping; the others wait for it
            c = self.store.control()
            if c.get("action") != "pause":
                if c.get("action") == "stop":
                    raise RunStopped(c.get("reason") or "stopped by the user")
                return
            t0 = time.monotonic()
            self.store.update_meta(status="paused", paused_at=_now())
            self.store.emit({"type": "run_paused", "stage": self._stage, "reason": c.get("reason") or "paused by the user"})
            while True:
                await asyncio.sleep(0.5)
                c = self.store.control()
                if c.get("action") == "stop":
                    self._paused_total += time.monotonic() - t0
                    raise RunStopped(c.get("reason") or "stopped by the user")
                if c.get("action") != "pause":
                    break
            waited = time.monotonic() - t0
            self._paused_total += waited
            if self._stage is not None and self._s0 is not None:
                self._s0 += waited  # paused time is not stage time
            self.store.update_meta(status="running", paused_at=None)
            self.store.emit({"type": "run_resumed", "stage": self._stage, "paused_s": round(waited, 1)})

    def _close_stage(self, *, completed: bool) -> float:
        if self._stage is None:
            return 0.0
        secs = time.monotonic() - self._s0
        st = self._timing.setdefault("stages", {}).setdefault(
            self._stage, {"wall_seconds": 0.0, "last_wall_seconds": None, "runs": 0, "completed": 0})
        st["wall_seconds"] = round(st["wall_seconds"] + secs, 3)
        st["runs"] += 1
        self.llm.usage.current_stage = None
        if completed:
            st["completed"] += 1
            st["last_wall_seconds"] = round(secs, 3)
        self._stage = None
        return secs

    def _checkpoint(self, **kw) -> None:
        self._timing["wall_seconds"] = round(self._wall0 + time.monotonic() - self._t0 - self._paused_total, 3)
        self.store.update_meta(usage=_sum_usage(self._base_usage, self.llm.usage.to_dict()), timing=self._timing,
                               seconds=round(self._timing["wall_seconds"], 1),
                               model_behaviour=self.llm.export_behaviour(), **kw)

    def _fail(self, status: str, exc: BaseException) -> None:
        self._close_stage(completed=False)
        self._checkpoint(status=status, error=f"{type(exc).__name__}: {exc}")
        self.store.emit({"type": "run_failed", "status": status, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc()[-2000:]})


def _steered(config: PipelineConfig, name: str, sc: StageConfig) -> StageConfig:
    """The stage's settings with the effort raised for the run's measure priorities (not saved:
    run.json keeps the settings as chosen; priorities.describe() lists what they change)."""
    from psalm_saga.priorities import steered_params

    if not config.priorities:
        return sc
    return sc.model_copy(update={"params": steered_params(config.priorities, name, dict(sc.params))})


def _stage_delta(before: dict, after: dict, stage: str) -> dict:
    a, b = after.get(stage, {}), before.get(stage, {})
    return {k: round(a.get(k, 0) - b.get(k, 0), 6) for k in ("calls", "prompt_tokens", "completion_tokens", "cost_usd")}


def _diff_usage(after: dict, before: dict) -> dict:
    """after − before, recursing into nested breakdowns."""
    out: dict = {}
    for k, v in after.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            d = round(v - (before.get(k) or 0), 6)
            if d:
                out[k] = d
        elif isinstance(v, dict):
            sub = _diff_usage(v, before.get(k) or {})
            if sub:
                out[k] = sub
    return out


def _sum_usage(a: dict, b: dict) -> dict:
    """Add usage dicts, recursing into nested breakdowns (by_stage, by_tag)."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            out[k] = round((out.get(k) or 0) + v, 6)
        elif isinstance(v, dict):
            out[k] = _sum_usage(out.get(k) or {}, v)
    return out
