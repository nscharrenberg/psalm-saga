"""Web app: create runs, watch them live, read and edit every artifact, compare experiments.

The server is a thin layer over the SDK. Runs execute as background tasks in the
server's event loop; progress is streamed from each run's events.jsonl over SSE, so a
run started from the CLI shows up live in the browser too.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from psalm_saga.config import load_config, preset_names
from psalm_saga.sdk import EDITABLE, Run, Saga
from psalm_saga.stages import available
from psalm_saga.taxonomy import load_taxonomy

STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    rerun_from: str | None = None
    until: str | None = None
    overrides: dict[str, Any] | None = None


class FixRequest(BaseModel):
    id: str | None = None  # one fix
    ids: list[str] = []  # or several at once (applied together, from the earliest stage)


class KeyRequest(BaseModel):
    var: str
    value: str = ""  # empty removes the saved value


class JudgeRequest(BaseModel):
    model: str = ""
    instruments: list[str] = ["psalm", "content", "style"]
    panel: list[str | dict] | None = None  # further judges; None = keep the run's setting


class ControlRequest(BaseModel):
    action: str  # pause | pause_after_stage | resume | stop | stop_after_stage


class ConfigRequest(BaseModel):
    overrides: dict[str, Any] = {}


class QueueSettings(BaseModel):
    max_parallel: int


class CheckRequest(BaseModel):
    preset: str = "full"
    overrides: dict[str, Any] = {}
    live: bool = True


class PlanRequest(BaseModel):
    name: str
    plan: dict[str, Any] | None = None  # the plan as a structure (the builder) ...
    yaml: str | None = None  # ... or as YAML text (edited by hand)


class ModelEntry(BaseModel):
    entry: dict[str, Any]


class DefaultTestsRequest(BaseModel):
    conditions: dict[str, str]  # name -> preset
    policies: dict[str, dict[str, str]] = {}
    margins: dict[str, float] = {}


class EditRequest(BaseModel):
    artifact: str
    instruction: str


def _priority_meta() -> dict:
    from dataclasses import asdict

    from psalm_saga.priorities import EFFECTS, PRIORITY_WEIGHT

    return {"weight": PRIORITY_WEIGHT, "effects": [asdict(e) for e in EFFECTS]}


def _psalm_scale() -> dict:
    from psalm_saga.eval.run_judges import EXPECTED, SCALE

    return {"scale": SCALE, "expected": EXPECTED}


def create_app(runs_dir: str | Path = "runs", experiments_dir: str | Path = "experiments") -> FastAPI:
    from psalm_saga import keys

    keys.load()  # the user's saved API keys and endpoints (see psalm_saga/keys.py)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="PSALM-SAGA", version="2")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    tasks: dict[str, asyncio.Task] = {}
    experiments_dir = Path(experiments_dir)
    exp_tasks: dict[str, asyncio.Task] = {}
    exp_logs: dict[str, list[str]] = {}

    def _run_dir(run_id: str) -> Path:
        p = (runs_dir / run_id).resolve()
        if runs_dir.resolve() not in p.parents or not (p / "run.json").exists():
            raise HTTPException(404, f"run {run_id} not found")
        return p

    def _open(run_id: str, overrides: dict | None = None) -> Run:
        return Saga.open(_run_dir(run_id), overrides=overrides)

    def _start(run: Run, **kw) -> None:
        if run.id in tasks and not tasks[run.id].done():
            raise HTTPException(409, "run is already executing")
        _dequeue(run.id)

        async def go():
            try:
                await run.arun(**kw)
            except asyncio.CancelledError:
                run.store.update_meta(status="cancelled", current_stage=None)
                run.store.emit({"type": "run_failed", "status": "cancelled", "error": "cancelled by user"})
            except Exception:
                pass  # recorded in run.json / events by the pipeline
            finally:
                asyncio.get_running_loop().call_soon(_pump)  # a slot is free: start the next queued run

        tasks[run.id] = asyncio.create_task(go())

    # ---------------------------------------------------------------- the run queue
    # New runs (one, or a batch from several files) start while fewer than `max_parallel` runs are
    # executing; the rest wait here, in order, and start as earlier ones end. A paused run still holds
    # its slot. "Continue" on a run starts it at once. The setting is kept in runs/queue.json; the queue
    # itself lives in memory: after a restart, runs still marked queued are shown as not started and are
    # started by hand (they never start spending on their own when the server comes up).
    queue: list[tuple[str, dict]] = []
    queue_file = runs_dir / "queue.json"

    def _max_parallel() -> int:
        try:
            return max(1, int(json.loads(queue_file.read_text(encoding="utf-8")).get("max_parallel", 1)))
        except (OSError, ValueError, TypeError, AttributeError):
            return 1

    def _executing() -> int:
        return sum(not t.done() for t in tasks.values())

    def _dequeue(run_id: str) -> bool:
        before = len(queue)
        queue[:] = [q for q in queue if q[0] != run_id]
        return len(queue) != before

    def _pump() -> None:
        while queue and _executing() < _max_parallel():
            run_id, kw = queue.pop(0)
            try:
                _start(_open(run_id), **kw)
            except HTTPException:
                continue  # deleted or already executing: next one

    def _enqueue(run: Run, **kw) -> None:
        queue.append((run.id, kw))
        _pump()
        if any(q[0] == run.id for q in queue):
            run.store.update_meta(status="queued")
            run.store.emit({"type": "run_queued", "position": len(queue)})

    from psalm_saga.store import RunStore

    for p in runs_dir.glob("*/run.json"):  # left queued by an earlier server: not started
        try:
            store = RunStore(p.parent)
            if store.meta().get("status") == "queued":
                store.update_meta(status="created")
        except (OSError, ValueError):
            continue

    @app.get("/api/queue")
    def get_queue():
        return {"max_parallel": _max_parallel(), "executing": _executing(), "queued": [q[0] for q in queue]}

    @app.put("/api/queue")
    async def put_queue(req: QueueSettings):  # async: starting runs needs the event loop
        if req.max_parallel < 1:
            raise HTTPException(400, "at least one run must be able to execute")
        queue_file.write_text(json.dumps({"max_parallel": req.max_parallel}), encoding="utf-8")
        _pump()  # a higher limit starts waiting runs now
        return get_queue()

    # ---------------------------------------------------------------- meta

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/meta")
    def meta():
        tax = load_taxonomy("psalm")
        return {
            "presets": [{"name": n, "description": " ".join(load_config(n).description.split()),
                         "config": load_config(n).model_dump(mode="json")} for n in preset_names()],
            "stages": available(),
            "taxonomy": tax.model_dump(),
            "editable": list(EDITABLE),
            "evaluation": __import__("psalm_saga.eval.grading", fromlist=["catalogue"]).catalogue(),
            "help": __import__("psalm_saga.web.help", fromlist=["help_bundle"]).help_bundle(),
            "priorities": _priority_meta(),
            "psalm_scale": _psalm_scale(),
            "settings": __import__("psalm_saga.settings_catalog", fromlist=["catalogue"]).catalogue(),
        }

    # ---------------------------------------------------------------- runs

    @app.get("/api/runs")
    def list_runs():
        out = Saga.list_runs(runs_dir)
        for r in out:
            # the folder is the address: a run folder that was renamed or copied stays reachable
            if r.get("path"):
                r["id"] = Path(r["path"]).name
            r["executing"] = r["id"] in tasks and not tasks[r["id"]].done()
            pos = next((i for i, q in enumerate(queue) if q[0] == r["id"]), None)
            r["queue_position"] = None if pos is None else pos + 1
        return sorted(out, key=lambda r: r.get("created") or "", reverse=True)

    @app.post("/api/runs")
    async def create_run(
        text: str = Form(""),
        kind: str = Form("auto"),
        preset: str = Form("full"),
        overrides: str = Form("{}"),
        until: str = Form(""),
        start: bool = Form(True),
        file: UploadFile | None = File(None),
        files: list[UploadFile] | None = File(None),
    ):
        """One run, or a batch: with several files, one run per file, all with exactly the same
        settings. Runs start through the queue (see /api/queue)."""
        uploads = [f for f in [file, *(files or [])] if f is not None and f.filename]
        inputs: list[tuple[str | None, str, str]] = []  # (file name, kind, text)
        for f in uploads:
            body = (await f.read()).decode("utf-8", errors="replace")
            k = "spec" if kind == "auto" and f.filename.endswith(".json") else kind
            inputs.append((f.filename, k, body))
        if not uploads:
            inputs.append((None, kind, text))
        for name, k, body in inputs:  # check every input before creating any run
            if not body.strip():
                raise HTTPException(400, f"empty input{f': {name}' if name else ''}")
            if k == "spec":
                try:
                    json.loads(body)
                except ValueError as exc:
                    raise HTTPException(400, f"{name or 'the specification'} is not valid JSON: {exc}") from exc
        try:
            ov = json.loads(overrides or "{}")
            saga = Saga(preset, overrides=ov, runs_dir=runs_dir)
        except Exception as exc:
            raise HTTPException(400, f"invalid configuration: {exc}") from exc
        batch = f"batch-{uuid.uuid4().hex[:8]}" if len(inputs) > 1 else None
        ids = []
        for name, k, body in inputs:
            if k == "auto":
                k = "premise" if len(body.split()) < 400 else "source"
            run = saga.create(**({"spec": json.loads(body)} if k == "spec" else {k: body}))
            if name or batch:
                run.store.update_meta(**({"input_name": name} if name else {}), **({"batch": batch} if batch else {}))
            ids.append(run.id)
            if start:
                _enqueue(run, until=until or None)
        return {"id": ids[0], "ids": ids, "batch": batch, "queued": [q[0] for q in queue if q[0] in ids]}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = _open(run_id)
        st = run.status()
        st["executing"] = run_id in tasks and not tasks[run_id].done()
        pos = next((i for i, q in enumerate(queue) if q[0] == run_id), None)
        st["queue_position"] = None if pos is None else pos + 1
        st["meta"] = run.store.meta()
        st["missing_stages"] = run.pipeline.missing_stages()
        st["artifacts"] = sorted(a for a in (p.relative_to(run.path).as_posix() for p in run.path.rglob("*")
                                             if p.is_file() and p.name != "events.jsonl") if not a.startswith("calls/"))
        return st

    @app.post("/api/runs/{run_id}/upgrade")
    async def upgrade(run_id: str):
        """Give an older run the stages its preset has gained since; affected stages will rerun."""
        added = _open(run_id).pipeline.adopt_missing_stages()
        return {"added": added}

    @app.post("/api/runs/{run_id}/run")
    async def run_run(run_id: str, req: RunRequest):
        run = _open(run_id, req.overrides)
        _start(run, rerun_from=req.rerun_from, until=req.until)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/control")
    async def control(run_id: str, req: ControlRequest):
        """Pause (now: calls in flight finish, new ones wait; or after the current stage), resume, or
        stop cleanly (now or after the current stage). A stopped run keeps its finished work and can be
        continued with /run."""
        run = _open(run_id)
        executing = run_id in tasks and not tasks[run_id].done()
        if req.action == "resume":
            run.resume()
            return {"ok": True}
        if req.action not in ("pause", "pause_after_stage", "stop", "stop_after_stage"):
            raise HTTPException(400, f"unknown action {req.action!r}")
        if not executing:
            raise HTTPException(409, "the run is not executing")
        if req.action.startswith("pause"):
            run.pause(after_stage=req.action.endswith("after_stage"))
        else:
            run.stop(after_stage=req.action.endswith("after_stage"))
        return {"ok": True}

    @app.post("/api/runs/{run_id}/check")
    async def check_run(run_id: str, live: bool = True):
        """Pre-flight check of the run's settings for the stages it still has to do."""
        return await _open(run_id).acheck(live=live)

    @app.post("/api/check")
    async def check_new(req: CheckRequest):
        """Pre-flight check of settings for a new run (before it is created)."""
        from psalm_saga.preflight import preflight

        try:
            cfg = load_config(req.preset, req.overrides or None)
        except Exception as exc:
            return {"ok": False, "problems": [{"severity": "error", "where": "settings", "message": str(exc)[:600], "hint": ""}],
                    "models": []}
        stages = [n for n, sc in cfg.stages.items() if sc.enabled]
        return await preflight(cfg, stages=stages, live=req.live)

    @app.put("/api/runs/{run_id}/config")
    async def put_config(run_id: str, req: ConfigRequest):
        """Change a run's settings (dotted keys, e.g. {"models.default.name": "openai/gpt-5.5"}) while it is
        not executing — for example after a failed pre-flight check or a crash — so it can be continued
        instead of started over. Finished stages are kept; what the changes affect is redone when they
        are rerun from the stage concerned."""
        if run_id in tasks and not tasks[run_id].done():
            raise HTTPException(409, "pause and stop the run before changing its settings")
        try:
            run = _open(run_id, req.overrides)
        except Exception as exc:
            raise HTTPException(400, f"invalid settings: {exc}") from exc
        meta = run.store.meta()
        if meta.get("status") in ("needs_attention",):
            run.store.update_meta(status="stopped", error=None)
        return {"ok": True, "config": run.store.meta().get("config")}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        if _dequeue(run_id):  # waiting in the queue: it simply does not start
            store = RunStore(_run_dir(run_id))
            store.update_meta(status="created")
            store.emit({"type": "run_dequeued"})
        t = tasks.get(run_id)
        if t and not t.done():
            t.cancel()
        return {"ok": True}

    @app.delete("/api/runs/{run_id}")
    async def delete(run_id: str):
        import shutil

        _dequeue(run_id)
        await cancel(run_id)
        shutil.rmtree(_run_dir(run_id))
        return {"ok": True}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, since: int = 0):
        path = _run_dir(run_id) / "events.jsonl"

        async def stream():
            # Tail the file by byte offset: a long run writes thousands of events, and re-reading
            # the whole file twice a second per open browser tab would grow with it.
            offset, skip, buf = 0, since, b""
            idle = 0
            while True:
                fresh = []
                if path.exists():
                    with open(path, "rb") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                    offset += len(chunk)
                    buf += chunk
                    *done, buf = buf.split(b"\n")
                    for raw in done:
                        if not raw.strip():
                            continue
                        if skip > 0:
                            skip -= 1
                            continue
                        fresh.append(raw.decode("utf-8", errors="replace").rstrip("\r"))
                for line in fresh:
                    yield f"data: {line}\n\n"
                if fresh:
                    idle = 0
                # a queued run counts as executing: the page follows it when it starts
                executing = (run_id in tasks and not tasks[run_id].done()) or any(q[0] == run_id for q in queue)
                idle += 1
                if not executing and idle > 20:
                    yield "event: idle\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- artifacts

    @app.get("/api/runs/{run_id}/artifact/{name:path}")
    def get_artifact(run_id: str, name: str):
        run = _open(run_id)
        if name.startswith("chapter:") or name in EDITABLE:
            a = run.artifact(name)
            if a is None:
                raise HTTPException(404, f"{name} not available yet")
            return json.loads(a.model_dump_json())
        p = (run.path / name).resolve()
        if run.path not in p.parents or not p.is_file():
            raise HTTPException(404, f"{name} not found")
        if p.suffix == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        return PlainTextResponse(p.read_text(encoding="utf-8"))

    @app.put("/api/runs/{run_id}/artifact/{name:path}")
    def put_artifact(run_id: str, name: str, body: Any = Body(...)):
        run = _open(run_id)
        try:
            run.put(name, body)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "status": run.status()}

    @app.post("/api/runs/{run_id}/edit")
    async def edit(run_id: str, req: EditRequest):
        run = _open(run_id)
        new = await run.aedit(req.artifact, req.instruction)
        return json.loads(new.model_dump_json())

    @app.get("/api/runs/{run_id}/graph")
    def graph(run_id: str, which: str = "synthetic", format: str = "json", against: str = "design"):
        from psalm_saga.graph import to_graphml

        try:
            g = _open(run_id).graph(which, against=against)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if format == "graphml":
            return PlainTextResponse(to_graphml(g), media_type="application/xml",
                                     headers={"Content-Disposition": f'attachment; filename="{run_id}-{which}{"-" + against if which == "compare" else ""}.graphml"'})
        return g

    @app.post("/api/runs/{run_id}/fix")
    async def fix(run_id: str, req: FixRequest):
        """Apply one or several suggested fixes as a NEW VERSION of the run (the original is kept):
        the run is copied, the fixes' settings applied (replacing earlier fix instructions), and the
        pipeline redoes everything from the earliest stage any of them needs."""
        from psalm_saga.fixes import make_version

        store = _open(run_id).store
        ev = store.read_json("evaluation.json") if store.exists("evaluation.json") else {}
        wanted = [*([req.id] if req.id else []), *req.ids]
        chosen = [f for f in ev.get("fixes", []) if f["id"] in wanted]
        missing = set(wanted) - {f["id"] for f in chosen}
        if not chosen or missing:
            raise HTTPException(404, f"No suggested fix {sorted(missing) or wanted!r} for this run")
        new_id, rerun_from, _ = make_version(runs_dir, _run_dir(run_id).name, chosen)
        run = _open(new_id)
        _start(run, rerun_from=rerun_from)
        return {"ok": True, "id": new_id, "rerun_from": rerun_from, "applied": [f["id"] for f in chosen]}

    # ---------------------------------------------------------------- API keys (kept on this machine)

    @app.get("/api/keys")
    def get_keys():
        """Which providers are configured; values are masked and never returned in full."""
        return {"providers": keys.status(), "file": str(keys.path())}

    @app.put("/api/keys")
    def put_key(req: KeyRequest):
        try:
            keys.set_value(req.var, req.value)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"providers": keys.status(), "warning": keys.problem(req.var, keys.clean(req.var, req.value))}

    @app.post("/api/keys/{var}/check")
    async def check_key(var: str):
        """Ask the provider whether it accepts the key (no model call, no cost)."""
        if var not in keys.known_vars() or not keys.can_check(var):
            raise HTTPException(400, f"{var} cannot be checked on its own; use Test on a model instead")
        return await keys.check(var)

    # ---------------------------------------------------------------- model library

    @app.get("/api/models")
    def list_models():
        """The model library: every model described once (built-in and the user's), with whether its
        provider's key or address is set."""
        from psalm_saga import model_library as ml

        ready = {p["id"]: p["ready"] for p in keys.status()}
        prov = {"hosted_vllm": "vllm", "ollama_chat": "ollama", "ollama": "ollama"}
        out = []
        for e in ml.library().values():
            p = e["name"].split("/", 1)[0]
            p = prov.get(p, p)
            needs = p not in ("fake", "ollama", "vllm") and not e.get("api_base")
            out.append({**e, "provider": p, "key_ready": (not needs) or ready.get(p, False)})
        return {"models": sorted(out, key=lambda m: (m.get("kind") != "api", m["label"].lower())), "file": str(ml.path())}

    @app.put("/api/models/{alias}")
    def put_model(alias: str, req: ModelEntry):
        from psalm_saga import model_library as ml

        try:
            return ml.save(alias, req.entry)
        except (ValueError, Exception) as exc:
            raise HTTPException(400, str(exc)[:500]) from exc

    @app.delete("/api/models/{alias}")
    def delete_model(alias: str):
        from psalm_saga import model_library as ml

        ml.delete(alias)
        return {"ok": True}

    @app.post("/api/models/{alias}/test")
    async def test_model(alias: str):
        """One tiny call ("reply with OK") to check the model's name, key and address."""
        from psalm_saga import model_library as ml
        from psalm_saga.config import PipelineConfig
        from psalm_saga.preflight import live_checks

        e = ml.get(alias)
        if not e:
            raise HTTPException(404, f"no model {alias}")
        cfg = PipelineConfig(models={"default": ml.to_model_config(e)})
        probs, results = await live_checks(cfg, {f"model library: {alias}": cfg.models["default"]})
        return {"ok": not any(p.severity == "error" for p in probs), "problems": [p.__dict__ for p in probs],
                "results": results}

    @app.post("/api/runs/{run_id}/judge")
    async def judge(run_id: str, req: JudgeRequest):
        """Run the (optional) model judges on a finished run: only the evaluation is redone; the text
        is not touched. The judge model is recorded in the run's settings."""
        if not req.instruments:
            raise HTTPException(400, "Choose at least one judge")
        ov = {"judges.enabled": True, "judges.instruments": req.instruments}
        if req.model.strip():
            ov["judges.model"] = req.model.strip()
        if req.panel is not None:
            ov["judges.panel"] = req.panel
        run = _open(run_id, ov)
        _start(run, only=["evaluate"])
        return {"ok": True}

    @app.get("/api/runs/{run_id}/versions")
    def versions(run_id: str):
        """The run's family (original and its fixed versions), and how this version compares with
        the one it was made from."""
        from psalm_saga.fixes import base_id, compare_evaluations

        me = _open(run_id).store.meta()
        root = me.get("root") or base_id(run_id)
        fam = sorted([r for r in Saga.list_runs(runs_dir) if (r.get("root") or base_id(r["id"])) == root
                      and (r["id"] == root or r.get("parent"))], key=lambda r: r.get("version") or 1)
        out = {"family": [{"id": r["id"], "version": r.get("version") or 1, "parent": r.get("parent"),
                           "fixes": r.get("fix_titles") or r.get("fixes") or [], "status": r.get("status")} for r in fam]}
        parent = me.get("parent")
        if parent and (runs_dir / parent / "evaluation.json").exists() and (runs_dir / run_id / "evaluation.json").exists():
            old = json.loads((runs_dir / parent / "evaluation.json").read_text(encoding="utf-8"))
            new = json.loads((runs_dir / run_id / "evaluation.json").read_text(encoding="utf-8"))
            out["compared_with"] = parent
            out["comparison"] = compare_evaluations(old, new)
        return out

    @app.post("/api/runs/{run_id}/recover")
    async def recover(run_id: str):
        """Start re-extracting the story bible from the synthetic text in the background (stage
        `recover`, then `evaluate`). Progress arrives as run events; poll the run for status."""
        run = _open(run_id)
        if run.recovered_bible() is not None:
            return {"status": "done"}
        if not run.story:
            raise HTTPException(404, "No synthetic story yet")
        from psalm_saga.config import StageConfig

        stages = run.pipeline.config.stages
        if "recover" not in stages or not stages["recover"].enabled:
            stages["recover"] = StageConfig()
        _start(run, only=["recover", "evaluate"])
        return {"status": "started"}

    @app.get("/api/runs/{run_id}/bundle")
    def bundle(run_id: str, kind: str = "full"):
        from fastapi.responses import Response

        from psalm_saga.bundle import build_bundle

        data = build_bundle(_run_dir(run_id), release=kind == "release")
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}-{kind}.zip"'})

    @app.get("/api/runs/{run_id}/download/{name}")
    def download(run_id: str, name: str):
        p = _run_dir(run_id) / name
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, filename=f"{run_id}-{name}")

    # ---------------------------------------------------------------- experiments

    @app.get("/api/experiments")
    def experiments():
        out, seen = [], set()
        for p in _experiment_summaries():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("name") in seen:
                continue
            seen.add(data.get("name"))
            out.append({"path": str(p.parent), "name": data.get("name"), "jobs": data.get("jobs"),
                        "failed": data.get("failed"), "has_report": (p.parent / "report.html").exists()})
        return out

    # ---------------------------------------------------------------- experiment builder

    def _plan_path(name: str) -> Path:
        import re as _re

        if not _re.fullmatch(r"[\w.-]{1,80}", name or ""):
            raise HTTPException(400, "an experiment name uses letters, digits, '-', '_' and '.' only")
        return experiments_dir / f"{name}.yaml"

    def _describe(path: Path) -> dict:
        from psalm_saga.experiments.runner import expand, load_plan

        plan, out = load_plan(path)
        jobs = expand(plan, path.parent)
        done = 0
        if (out / "runs").exists():
            for j in jobs:
                rj = out / "runs" / j.run_id / "run.json"
                if rj.exists():
                    try:
                        done += json.loads(rj.read_text(encoding="utf-8")).get("status") == "done"
                    except (OSError, json.JSONDecodeError):
                        pass
        items = sorted({j.item for j in jobs})
        return {"name": path.stem, "path": str(path), "output": str(out), "jobs": len(jobs), "done": done,
                "items": items, "conditions": list(plan.conditions), "models": list(plan.models),
                "tests": len(plan.hypotheses) if isinstance(plan.hypotheses, list) else 0,
                "running": path.stem in exp_tasks and not exp_tasks[path.stem].done(),
                "has_report": (out / "report.html").exists(), "log": exp_logs.get(path.stem, [])[-30:]}

    @app.get("/api/experiment-plans")
    def list_plans():
        out = []
        for p in sorted(experiments_dir.glob("*.yaml")):
            try:
                out.append(_describe(p))
            except Exception as exc:  # a broken plan is listed with its error, not hidden
                out.append({"name": p.stem, "path": str(p), "error": str(exc)[:300]})
        return out

    @app.get("/api/experiment-plans/{name}")
    def get_plan(name: str):
        p = _plan_path(name)
        if not p.exists():
            raise HTTPException(404, f"no experiment plan {name}")
        text = p.read_text(encoding="utf-8")
        try:
            info = _describe(p)
        except Exception as exc:
            info = {"error": str(exc)[:500]}
        return {"yaml": text, "plan": yaml.safe_load(text), **info}

    @app.post("/api/experiment-plans")
    def save_plan(req: PlanRequest):
        """Save a plan (from the builder or as YAML) after validating it; returns what it would run."""
        from psalm_saga.experiments.runner import ExperimentPlan

        p = _plan_path(req.name)
        text = req.yaml if req.yaml is not None else yaml.safe_dump({"name": req.name, **(req.plan or {})},
                                                                       sort_keys=False, allow_unicode=True, width=120)
        try:
            data = yaml.safe_load(text)
            data["name"] = req.name
            ExperimentPlan.model_validate(data)
        except Exception as exc:
            raise HTTPException(400, f"invalid plan: {exc}"[:1500]) from exc
        experiments_dir.mkdir(parents=True, exist_ok=True)
        if req.yaml is None:
            text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
        p.write_text(text, encoding="utf-8")
        try:
            return {"ok": True, **_describe(p)}
        except Exception as exc:
            raise HTTPException(400, f"saved, but the plan cannot be expanded: {exc}"[:1500]) from exc

    @app.post("/api/experiment-plans/{name}/inputs")
    async def upload_inputs(name: str, files: list[UploadFile] = File(...)):
        """Texts for an experiment, saved to experiments/inputs/<name>/; the plan reads them with a glob."""
        _plan_path(name)
        folder = experiments_dir / "inputs" / name
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            fn = Path(f.filename or "text.txt").name
            data = await f.read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            (folder / (Path(fn).stem + ".txt")).write_text(text, encoding="utf-8")
            saved.append(Path(fn).stem + ".txt")
        return {"folder": str(folder), "glob": f"inputs/{name}/*.txt", "saved": saved}

    @app.post("/api/experiment-plans/default-tests")
    def default_tests(req: DefaultTestsRequest):
        from psalm_saga.experiments.hypotheses import default_hypotheses

        return {"hypotheses": default_hypotheses(req.conditions, req.policies, req.margins)}

    @app.post("/api/experiment-plans/{name}/start")
    async def start_plan(name: str, judge: bool = True):
        from psalm_saga.experiments.runner import run_experiment

        p = _plan_path(name)
        if not p.exists():
            raise HTTPException(404, f"no experiment plan {name}")
        if name in exp_tasks and not exp_tasks[name].done():
            raise HTTPException(409, "this experiment is already running")
        log = exp_logs.setdefault(name, [])

        async def go():
            try:
                await run_experiment(p, judge=judge, console=type("C", (), {"print": staticmethod(lambda *a: log.append(" ".join(map(str, a))))})())
                log.append("finished")
            except Exception as exc:
                log.append(f"failed: {exc}")

        exp_tasks[name] = asyncio.create_task(go())
        return {"ok": True}

    @app.post("/api/experiment-plans/{name}/stop")
    async def stop_plan(name: str):
        t = exp_tasks.get(name)
        if not t or t.done():
            raise HTTPException(409, "this experiment is not running")
        t.cancel()
        exp_logs.setdefault(name, []).append("stopped; starting it again continues where it stopped")
        return {"ok": True}

    def _experiment_summaries() -> list[Path]:
        return sorted(Path(".").glob("experiments_out/*/summary.json")) + sorted(runs_dir.glob("../experiments_out/*/summary.json"))

    @app.get("/experiments/{name}/report.html")
    def experiment_report(name: str):
        from fastapi.responses import HTMLResponse

        for p in _experiment_summaries():
            if p.parent.name == name and (p.parent / "report.html").exists():
                return HTMLResponse((p.parent / "report.html").read_text(encoding="utf-8"))
        raise HTTPException(404, "No report for this experiment")

    return app
