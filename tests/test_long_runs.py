"""Bounding long runs (early-stopping conform, timeout cap, time limit, workload warning, review
progress) and a panel of judges in the evaluation."""

import time
from pathlib import Path

import pytest

from psalm_saga.config import ModelConfig, PipelineConfig, load_config
from psalm_saga.llm import LLM, LLMError, Part
from psalm_saga.llm.limiter import LimiterRegistry
from psalm_saga.pipeline import Pipeline
from psalm_saga.preflight import static_checks, workload
from tests.conftest import FAKE

DATA = Path(__file__).parent / "data"
SRC = (DATA / "en_harbour.txt").read_text(encoding="utf-8")


async def test_a_call_that_keeps_timing_out_fails_fast_with_advice():
    cfg = PipelineConfig(models={"default": ModelConfig(name="fake/t", timeout_s=0.1, max_retries=8, timeout_retries=1,
                                                        extra={"fake_hang_every": 1})})
    llm = LLM(cfg, limiters=LimiterRegistry())
    t0 = time.monotonic()
    with pytest.raises(LLMError, match="timeout_s"):
        await llm.text("draft", "s", [Part("p")])
    assert time.monotonic() - t0 < 5                      # 2 attempts, not 9


async def test_conform_stops_when_rounds_stop_paying_off(runs):
    p = Pipeline.create("full", runs_dir=runs, source=SRC, run_id="early",
                        overrides=[*FAKE, "stages.conform.params.rounds=6", "stages.conform.params.tolerance=0.0001"])
    await p.run(until="conform")
    logs = [p.store.read_json(f"conform/{f.name}") for f in p.store.glob("conform/ch_*.json")]
    assert logs and sum(len(lg["rounds"]) for lg in logs) < 6 * len(logs)
    assert any(lg.get("stopped") and len(lg["rounds"]) < 6 for lg in logs)


async def test_time_limit_stops_the_run_and_continuing_finishes_it(runs):
    p = Pipeline.create("full", runs_dir=runs, source=SRC, run_id="timed",
                        overrides=[*FAKE, "limits.max_minutes=0.004", "models.default.extra.fake_latency_s=0.05"])
    await p.run()
    assert p.store.meta()["status"] == "stopped"
    again = Pipeline.open(p.store.root, overrides=["limits.max_minutes=null"])
    await again.run()
    assert again.store.meta()["status"] == "done"


def test_workload_warning_for_a_heavy_configuration():
    heavy = load_config("full", ["models.default.name=openai/x", "models.default.extra.reasoning_effort=high",
                                 'priorities=["form", "style", "distance"]'])
    st = list(heavy.stages)
    w = workload(heavy, st)
    assert w["passes"] == 2 and w["worst"] > 20
    assert any(p.where == "workload" for p in static_checks(heavy, stages=st))
    light = load_config("full", ["models.default.name=openai/x", "stages.review.params.max_backtracks=0"])
    assert not any(p.where == "workload" for p in static_checks(light, stages=list(light.stages)))


async def test_review_reports_progress(runs):
    events = []
    p = Pipeline.create("full", runs_dir=runs, source=SRC, run_id="prog", overrides=FAKE, on_event=events.append)
    await p.run(until="review")
    prog = [e for e in events if e.get("type") == "stage_progress" and e.get("stage") == "review"]
    assert prog and prog[-1]["done"] == prog[-1]["total"]


async def test_judge_panel_gives_results_per_judge_and_agreement(runs):
    p = Pipeline.create("full", runs_dir=runs, source=SRC, run_id="panel",
                        overrides=[*FAKE, "judges.enabled=true", "judges.model=fake/primary",
                                   'judges.panel=["fake/second", {"name": "fake/third", "api_base": "http://localhost:9"}]'])
    await p.run()
    jd = p.store.read_json("evaluation.json")["judges"]
    assert [j["model"] for j in jd["per_judge"]] == ["fake/primary", "fake/second", "fake/third"]
    assert len(jd["panel"]) == 2 and "psalm" in jd["panel"][0]
    ag = jd["agreement"]
    assert ag["judges"] == 3 and "psalm_function_alpha" in ag and ag["psalm_function"]["n"] == 3
    assert p.config.models["judge_3"].extra.get("api_base") == "http://localhost:9"


# ------------------------------------------------------------------ the experimental design

async def test_no_graph_writes_without_the_graph_but_measures_it(runs):
    p = Pipeline.create("no_graph", runs_dir=runs, source=SRC, run_id="nog", overrides=FAKE)
    await p.run()
    assert p.store.exists("bible.json") and p.store.read_json("bible.json")["entities"]   # still built
    calls = [p.store.read_json(f"calls/{f.name}") for f in p.store.glob("calls/*.json")]
    drafts = [c for c in calls if str(c.get("tag", "")).startswith("draft:ch")]
    assert drafts and not any("Facts of the story design" in str(c["messages"]) for c in drafts)
    assert not any("# Entities" in str(c["messages"]) or "# Relations" in str(c["messages"]) for c in drafts)
    plans = [c for c in calls if str(c.get("tag", "")).startswith("plan:")]
    assert plans and not any("# Entities" in str(c["messages"]) or "Event:" in str(c["messages"]) for c in plans)
    assert p.store.meta()["status"] == "done"


def test_single_call_is_told_the_policy():
    from psalm_saga.stages.baselines import policy_brief

    assert policy_brief({"character": "preserve"}) == ""
    txt = policy_brief({"writing_style": "preserve", "character": "abstract", "plot_structure": "regenerate"})
    assert "characters: keep what it does" in txt and "plot structure: replace it" in txt


async def test_experiment_crosses_policies_and_tests_hypotheses(tmp_path):
    import json
    import shutil

    from psalm_saga.experiments.runner import run_experiment

    shutil.copytree(DATA, tmp_path / "data")
    plan = tmp_path / "plan.yaml"
    plan.write_text(f"""
name: h
output: {tmp_path / 'out'}
inputs: [{{glob: "data/en_*.txt", kind: source}}, {{glob: "data/nl_[bs]*.txt", kind: source}}]
policies: {{preserve: {{all: preserve}}, replace: {{all: regenerate, writing_style: preserve, narrative_voice: preserve}}}}
conditions: {{full: {{preset: full}}, no_feedback: {{preset: no_feedback}}, para: {{preset: paraphrase, policies: [preserve]}}}}
models: {{fake: {{models.default.name: fake/x}}}}
bootstrap: 500
hypotheses:
  - {{id: A, family: H1, measure: kg_events, a: full@preserve, b: no_feedback@preserve}}
  - {{id: B, family: H1, measure: sentence_overlap, a: full@replace, b: no_feedback@replace, test: non_inferiority, margin: 0.5}}
  - {{id: C, family: H4, measure: span, a: full@preserve, test: share_below, value: 12, share: 0.95}}
""")
    res = await run_experiment(plan, judge=False)
    assert res["jobs"] == 4 * 5                                # 2 + 2 + 1 conditions after crossing
    s = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    tests = {t["id"]: t for t in s["hypotheses"]["tests"]}
    assert tests["B"]["status"] == "ok" and tests["B"]["n"] == 4 and "p_holm" in tests["B"]
    assert tests["B"]["supported"] is True                     # same writer, a generous margin
    assert tests["C"]["supported"] is True
    assert "## Hypotheses" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    run = json.loads((tmp_path / "out" / "runs" / "en_harbour--full@replace--fake--r1" / "run.json").read_text())
    assert run["config"]["transform"]["policy"]["character"] == "regenerate"


def test_holm_and_kb_main_plan_loads():
    from psalm_saga.experiments.hypotheses import holm
    from psalm_saga.experiments.runner import load_plan

    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    plan, _ = load_plan(Path(__file__).parent.parent / "experiments" / "kb_main.yaml")
    assert "paraphrase@preserve" in plan.conditions and "paraphrase@replace" not in plan.conditions
    assert plan.conditions["full@reinvent"].overrides["transform.policy.character"] == "abstract"
    assert plan.conditions["full@reinvent"].overrides["transform.policy.writing_style"] == "preserve"
    conds = set(plan.conditions)
    assert all(h["a"] in conds and h.get("b", h["a"]) in conds for h in plan.hypotheses)


# ------------------------------------------------------------------ settings and the experiment builder

def test_every_stage_parameter_is_in_the_settings_catalogue():
    import re

    from psalm_saga.settings_catalog import STAGE_PARAMS

    root = Path(__file__).parent.parent / "psalm_saga" / "stages"
    stage_of = {"baselines": "draft"}
    missing = []
    for f in root.glob("*.py"):
        stage = stage_of.get(f.stem, f.stem)
        for k in re.findall(r'params\.get\("([a-z_]+)"', f.read_text(encoding="utf-8")):
            if k in ("variant", "fix_instruction", "rhythm_targets"):     # internal: set by fixes / old presets
                continue
            if k not in STAGE_PARAMS.get(stage, {}):
                missing.append(f"{stage}.{k}")
    assert not missing, missing


def test_web_settings_catalogue_and_experiment_builder(tmp_path):
    from fastapi.testclient import TestClient

    from psalm_saga.web.app import create_app

    c = TestClient(create_app(tmp_path / "runs", experiments_dir=tmp_path / "experiments"))
    meta = c.get("/api/meta").json()
    assert "review" in meta["settings"]["stages"] and "use_graph" in {f["key"] for f in meta["settings"]["run_fields"]}
    assert {"no_graph", "no_feedback"} <= {p["name"] for p in meta["presets"]}
    r = c.post("/api/experiment-plans/demo/inputs",
               files=[("files", ("a.txt", SRC.encode(), "text/plain")), ("files", ("b.txt", SRC.encode(), "text/plain"))])
    assert r.status_code == 200 and r.json()["glob"] == "inputs/demo/*.txt"
    plan = {"output": str(tmp_path / "out"), "inputs": [{"glob": "inputs/demo/*.txt"}],
            "policies": {"preserve": {"all": "preserve"}, "reinvent": {"all": "abstract", "writing_style": "preserve"}},
            "conditions": {"full": {"preset": "full"}, "single_call": {"preset": "flat"}},
            "models": {"fake": {"models.default.name": "fake/x"}}, "hypotheses": "default"}
    r = c.post("/api/experiment-plans", json={"name": "demo", "plan": plan})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["jobs"] == 2 * 4 and d["tests"] > 0 and "full@reinvent" in d["conditions"]
    assert (tmp_path / "experiments" / "demo.yaml").exists()
    bad = c.post("/api/experiment-plans", json={"name": "demo", "yaml": "conditions: 3"})
    assert bad.status_code == 400
    t = c.post("/api/experiment-plans/default-tests", json={"conditions": {"full": "full", "no_graph": "no_graph"},
                                                            "policies": {}}).json()["hypotheses"]
    assert t and all(h["family"] == "H2" for h in t)
    listed = c.get("/api/experiment-plans").json()
    assert listed[0]["name"] == "demo" and listed[0]["done"] == 0
