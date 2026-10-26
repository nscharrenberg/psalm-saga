"""Bible coverage in review, full call logs, and output allowance for reasoning models."""

import json

from psalm_saga.artifacts import Bible, ChapterPlan, ChapterReview, CoverageItem, ScenePlan
from psalm_saga.config import ModelConfig, PipelineConfig
from psalm_saga.llm.client import LLM
from psalm_saga.stages.review import coverage_issues, design_checklist


def _bible():
    return Bible.model_validate({
        "entities": [{"id": "a", "name": "Nathaniel", "kind": "character", "chapters": [1], "mentions": 9},
                     {"id": "b", "name": "the cook", "kind": "character", "chapters": [1], "mentions": 5},
                     {"id": "c", "name": "Nathaniel's chest", "kind": "object", "chapters": [1], "mentions": 3}],
        "relations": [{"source": "b", "target": "a", "type": "remembers"}],
        "chapters": [{"index": 1, "summary": "", "scenes": [{"summary": "", "characters": ["Nathaniel", "the cook"]}],
                      "events": [{"description": "Nathaniel falls from the yard"},
                                 {"description": "the crew searches the sea", "caused_by": "Nathaniel falls"}]}]})


def test_checklist_lists_events_causes_relations_and_world():
    plan = ChapterPlan(index=1, title="", summary="", scenes=[ScenePlan(summary="", characters=["Nathaniel"])])
    items = design_checklist(_bible(), plan)
    ids = [i["id"] for i in items]
    assert ids == ["E1", "E2", "C1", "R1", "W1"]
    assert "remembers" in items[3]["text"] and "chest" in items[4]["text"]


def test_coverage_becomes_routed_issues():
    plan = ChapterPlan(index=1, title="", summary="", scenes=[ScenePlan(summary="", characters=["Nathaniel"])])
    items = design_checklist(_bible(), plan)
    rev = ChapterReview(coverage=[CoverageItem(id="E1", status="contradicted", evidence="he jumps"),
                                  CoverageItem(id="C1", status="missing", in_plan=False),
                                  CoverageItem(id="R1", status="missing"), CoverageItem(id="W1", status="realised")])
    out = {i.commitment.split("]")[0][1:]: i for i in coverage_issues(items, rev)}
    assert out["E1"].severity == "blocker" and out["E1"].origin == "prose"
    assert out["C1"].severity == "major" and out["C1"].origin == "plan"   # the plan left it out -> re-plan
    assert out["R1"].severity == "minor" and "W1" not in out


def test_reasoning_models_get_headroom():
    cfg = PipelineConfig(models={"default": ModelConfig(name="fake/x", max_output_tokens=8000, min_output_tokens=2048,
                                                        reasoning_headroom=6000)})
    llm = LLM(cfg)
    mc = cfg.models["default"]
    assert llm.allowance(mc, 900) == 2048            # not reasoning: just the floor
    mc.reasoning = True
    assert llm.allowance(mc, 900) == 6900            # visible + headroom
    assert llm.allowance(mc, 5000) == 11000          # the cap rises with it


async def test_calls_are_logged_in_full_and_reasoning_is_detected(tmp_path):
    logged = {}
    events = []
    cfg = PipelineConfig(models={"default": ModelConfig(name="fake/x", extra={"fake_reasoning_tokens": 300})})
    llm = LLM(cfg, on_event=events.append, call_log=lambda cid, rec: logged.__setitem__(cid, json.loads(json.dumps(rec))))
    from psalm_saga.llm import Part

    await llm.text("default", "You write.", [Part("Write a line about the sea.")], max_tokens=200, hints={"target_words": 20}, tag="t:1")
    rec = next(iter(logged.values()))
    assert rec["status"] == "done" and rec["tag"] == "t:1"
    assert any("the sea" in json.dumps(m) for m in rec["messages"]) and rec["content"]
    assert rec["reasoning"] and rec["usage"]["reasoning_tokens"] == 300
    start = next(e for e in events if e["type"] == "llm_start")
    done = next(e for e in events if e["type"] == "llm_call")
    assert start["call"] == done["call"] == rec["id"] and done["reasoning_tokens"] == 300
    assert llm.is_reasoning(cfg.models["default"])   # learnt from the answer


async def test_run_keeps_call_logs_but_release_bundle_drops_them(runs, nl_text):
    import io
    import zipfile

    from psalm_saga.bundle import build_bundle
    from psalm_saga.pipeline import Pipeline
    from tests.conftest import FAKE

    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="trace")
    await p.run()
    calls = list((p.store.root / "calls").glob("*.json"))
    ev = [json.loads(line) for line in p.store.read_text("events.jsonl").splitlines()]
    ids = {e["call"] for e in ev if e["type"] == "llm_call" and e.get("call")}
    assert calls and ids <= {c.stem for c in calls}
    assert any(e["type"] == "review_result" and e.get("coverage") for e in ev)
    full = zipfile.ZipFile(io.BytesIO(build_bundle(p.store.root)))
    rel = zipfile.ZipFile(io.BytesIO(build_bundle(p.store.root, release=True)))
    assert any(n.startswith("calls/") for n in full.namelist())
    assert not any(n.startswith("calls/") for n in rel.namelist())


async def test_judges_are_optional_and_psalm_rates_every_dimension(runs, nl_text):
    from psalm_saga.eval.grading import grades
    from psalm_saga.pipeline import Pipeline
    from tests.conftest import FAKE

    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="nojudge")
    await p.run()
    ev = p.store.read_json("evaluation.json")
    assert "judges" not in ev and ev["not_measurable"]["psalm_fidelity"].startswith("the judges are off")

    p = Pipeline.create("full", runs_dir=runs, source=nl_text, run_id="judged",
                        overrides=[*FAKE, "judges.enabled=true", "judges.model=fake/judge"])
    await p.run()
    ev = p.store.read_json("evaluation.json")
    j = ev["judges"]
    assert j["model"] == "fake/judge" and not j["same_model_as_writer"]
    assert len(j["psalm"]["dimensions"]) == 6 and all(d["subdimensions"] for d in j["psalm"]["dimensions"])
    sub = j["psalm"]["dimensions"][0]["subdimensions"][0]
    assert {"in_a", "in_b", "evidence_a", "reasoning", "function_similarity", "expression_similarity"} <= set(sub)
    g = grades(ev)
    assert 0 <= g["psalm_fidelity"]["score"] <= 1 and "content" in j and "style" in j
