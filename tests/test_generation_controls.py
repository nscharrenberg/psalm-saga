"""Measure priorities, pre-flight checks, run control (pause / stop), scene measurements, real-world
names, and review conforming a redrafted chapter."""

import asyncio
import json
from pathlib import Path

import pytest

from psalm_saga.artifacts import ChapterReview, Entity, Issue, Rename, SceneNote, TransformMap
from psalm_saga.pipeline import Pipeline
from psalm_saga.preflight import PreflightFailed
from psalm_saga.priorities import PRIORITY_WEIGHT, resolve, steered_params, weight
from tests.conftest import FAKE

DATA = Path(__file__).parent / "data"


# ------------------------------------------------------------------ priorities

def test_priorities_resolve_groups_and_raise_effort_only():
    assert {"sentence_overlap", "style_drift"} <= resolve(["style"])
    assert resolve(["ngram8"]) == {"ngram8"}
    assert weight([], "style_drift") == 1.0 and weight(["style"], "style_drift") == PRIORITY_WEIGHT
    p = steered_params(["sentence_overlap"], "conform", {"rounds": 6, "tolerance": 0.12})
    assert p["rounds"] == 6 and p["tolerance"] == 0.06          # never lowers effort, tightens tolerance
    assert steered_params([], "conform", {"rounds": 2}) == {"rounds": 2}
    assert steered_params(["kg_events"], "review", {})["strict_coverage"] is True


async def test_priorities_steer_stages_and_show_in_evaluation(runs):
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, "priorities=[\"style\", \"ngram8\"]"], run_id="prio")
    by = {s.name: s for s in p.stages()}
    assert by["conform"].params["rounds"] >= 4 and by["guard"].params["rounds"] == 3
    assert p.config.stages["conform"].params.get("rounds", 2) == 2      # the saved settings are untouched
    await p.run()
    ev = p.store.read_json("evaluation.json")
    assert ev["priorities"] == ["style", "ngram8"] and ev["priority"]["n"] >= 1
    assert any(s["stage"] == "conform" for s in ev["steering"])
    assert ev["grades"]["ngram8"].get("priority") is True
    logs = [json.loads(f.read_text(encoding="utf-8")) for f in p.store.glob("conform/ch_*.json")]
    assert logs and logs[0]["weights"]["sentence_distribution"] == PRIORITY_WEIGHT


# ------------------------------------------------------------------ pre-flight

async def test_preflight_stops_a_misconfigured_run_and_a_settings_change_rescues_it(runs):
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=["models.default.name=nonexistent/model-x"], run_id="pf")
    with pytest.raises(PreflightFailed):
        await p.run()
    meta = p.store.meta()
    assert meta["status"] == "needs_attention" and "nonexistent" in meta["error"]
    rep = p.store.read_json("preflight.json")
    assert not rep["ok"] and rep["problems"][0]["where"] == "models.default"
    assert not p.store.exists("bible_source.json")                      # nothing was spent
    fixed = Pipeline.open(p.store.root, overrides=FAKE)
    await fixed.run()
    assert fixed.store.meta()["status"] == "done"


async def test_preflight_reports_a_missing_key(monkeypatch, tmp_path):
    from psalm_saga.config import load_config
    from psalm_saga.preflight import preflight

    monkeypatch.setenv("PSALM_SAGA_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rep = await preflight(load_config("full", ["models.default.name=anthropic/claude-sonnet-5-5"]),
                          stages=["extract"], live=False)
    assert not rep["ok"] and "ANTHROPIC_API_KEY" in rep["problems"][0]["message"]
    rep = await preflight(load_config("full", [*FAKE, "priorities=[\"nonsense\"]"]), stages=["extract"], live=False)
    assert not rep["ok"] and rep["problems"][0]["where"] == "priorities"


# ------------------------------------------------------------------ run control

async def test_pause_resume_and_stop(runs):
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, "models.default.extra.fake_latency_s=0.05", "cache=false"], run_id="ctl")
    task = asyncio.create_task(p.run())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if p.store.meta().get("current_stage") in ("spec", "transform", "plan"):
            break
    p.store.set_control("pause")
    for _ in range(100):
        await asyncio.sleep(0.05)
        if p.store.meta().get("status") == "paused":
            break
    assert p.store.meta()["status"] == "paused"
    n = len(p.store.events())
    await asyncio.sleep(0.6)
    assert not any(e["type"] == "llm_start" for e in p.store.events()[n:])     # nothing new while paused
    p.store.set_control(None)                                               # resume
    await asyncio.sleep(1.0)
    assert p.store.meta()["status"] == "running"
    p.store.set_control("stop")
    st = await asyncio.wait_for(task, 30)
    assert st["status"] == "stopped" and not p.store.exists("control.json")
    types = [e["type"] for e in p.store.events()]
    assert "run_paused" in types and "run_resumed" in types and "run_stopped" in types
    again = Pipeline.open(p.store.root)                                     # a stopped run continues
    await again.run()
    assert again.store.meta()["status"] == "done"


# ------------------------------------------------------------------ scene measurements and names

def test_scene_openings_are_measured_and_discarded():
    from psalm_saga.stages.extract import measure_scenes

    text = ("The boat left at dawn and the men rowed hard against the tide for an hour. " * 6
            + "\n\n“Where is he?” cried the cook. “Gone,” said John. " * 4
            + "\n\nThat night the narrator sat alone in the galley and thought about the dead man for a long while. " * 5)
    scenes = [SceneNote(summary="a", opening="The boat left at dawn and"),
              SceneNote(summary="b", opening="“Where is he?” cried the cook."),
              SceneNote(summary="c", opening="That night the narrator sat alone")]
    assert measure_scenes(text, scenes, "en") == 3
    assert all(s.opening == "" for s in scenes)                      # no source wording leaves the analysis
    assert sum(s.words for s in scenes) == len(text.split())
    assert scenes[1].dialogue > 0.2 and scenes[0].dialogue == 0.0
    assert scenes[2].sentence_words > scenes[1].sentence_words


def test_real_world_names_are_kept_and_places_are_not_split():
    from psalm_saga.stages.transform import complete_renames

    tmap = TransformMap(renames=[Rename(original="George Ballmer", new="William Hales"),
                                 Rename(original="Pacific", new="Indian Ocean", kind="place", real=True),
                                 Rename(original="Flying Dutchman", new="The Wraith", kind="other", real=True),
                                 Rename(original="Sea Witch", new="Night Heron", kind="place")])
    ents = [Entity(id="e1", name="George Ballmer", kind="character"),
            Entity(id="e2", name="Sea Witch", kind="place")]
    kept = complete_renames(tmap, ents, keep_real=True).as_dict()
    assert "Pacific" not in kept and "Flying Dutchman" not in kept
    assert kept["George"] == "William" and kept["Ballmer"] == "Hales"   # personal names: token forms
    assert "Sea" not in kept and "Witch" not in kept                    # invented place: whole name only
    renamed = complete_renames(tmap, ents, keep_real=False).as_dict()
    assert renamed["Pacific"] == "Indian Ocean"


# ------------------------------------------------------------------ review conforms a redraft

async def test_review_conforms_a_chapter_it_redrafts(runs, monkeypatch):
    import psalm_saga.stages.review as review

    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, "stages.review.params.max_backtracks=0"], run_id="rv")
    await p.run(until="conform")
    calls = {"conform": 0, "check": 0}

    async def check(self, ctx, spec_txt, plan_txt, cast, text, index, r, checklist=None):
        calls["check"] += 1
        bad = Issue(severity="major", origin="plan", commitment="E1 missing", evidence="", fix="add it")
        return ChapterReview(index=index, issues=[bad] if r == 0 else [])

    real = review.conform_text

    async def conform_text(ctx, stage, text, index, n_ch, **kw):
        calls["conform"] += 1
        return await real(ctx, stage, text, index, n_ch, **kw)

    monkeypatch.setattr(review.Review, "check", check)
    monkeypatch.setattr(review, "conform_text", conform_text)
    await p.run(only=["review"])
    rv = p.store.read_json("reviews/ch_001.json")
    assert any(r["action"] == "replan" for r in rv["rounds"])
    assert calls["conform"] >= 1                                     # the redraft was conformed before acceptance
    assert all("style_distance" in r for r in rv["rounds"] if r["action"] == "replan")
