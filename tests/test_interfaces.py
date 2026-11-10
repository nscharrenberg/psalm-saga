import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from psalm_saga.cli.main import app
from psalm_saga.experiments.runner import run_experiment
from psalm_saga.web.app import create_app
from tests.conftest import DATA


def test_cli_run_status_show(tmp_path):
    runner = CliRunner()
    src = DATA / "en_harbour.txt"
    res = runner.invoke(app, ["run", str(src), "-m", "fake/cli", "--runs-dir", str(tmp_path), "--id", "r1"])
    assert res.exit_code == 0, res.output
    assert "leakage" in res.output
    res = runner.invoke(app, ["status", str(tmp_path / "r1")])
    assert res.exit_code == 0 and "evaluate" in res.output
    res = runner.invoke(app, ["show", str(tmp_path / "r1"), "spec"])
    assert res.exit_code == 0
    res = runner.invoke(app, ["resume", str(tmp_path / "r1"), "--from", "assemble"])
    assert res.exit_code == 0
    res = runner.invoke(app, ["config", "no_review", "--set", "length.target_words=900"])
    assert "target_words: 900" in res.output


def test_cli_until_checkpoint(tmp_path):
    res = CliRunner().invoke(app, ["run", "Een vuurtorenwachter vindt een fles met een brief uit de toekomst.",
                                   "-m", "fake/cli", "--runs-dir", str(tmp_path), "--id", "p", "--until", "plan"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "p" / "plan.json").exists() and not (tmp_path / "p" / "story.md").exists()


def _wait(c, rid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"/api/runs/{rid}").json()
        if not st["executing"] and st.get("status") not in ("created", "running"):
            return st
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_web_api_end_to_end(tmp_path):
    book = (DATA / "de_muehle.txt").read_text(encoding="utf-8")
    with TestClient(create_app(tmp_path)) as c:
        assert "PSALM" in c.get("/").text
        meta = c.get("/api/meta").json()
        assert "full" in [p["name"] for p in meta["presets"]]
        rid = c.post("/api/runs", data={"text": book, "preset": "full",
                                        "overrides": json.dumps({"models.default.name": "fake/w"})}).json()["id"]
        st = _wait(c, rid)
        assert st["status"] == "done" and st["language"] == "de"
        assert c.get(f"/api/runs/{rid}/artifact/story.md").text.count("## Kapitel") == 4
        assert c.get(f"/api/runs/{rid}/artifact/evaluation.json").json()["language"]["ok"]
        spec = c.get(f"/api/runs/{rid}/artifact/spec").json()
        spec["dimensions"][0]["items"][0]["value"] = "Kurze, harte Sätze."
        assert c.put(f"/api/runs/{rid}/artifact/spec", json=spec).status_code == 200
        assert not {s["name"]: s["done"] for s in c.get(f"/api/runs/{rid}").json()["stages"]}["plan"]
        assert c.post(f"/api/runs/{rid}/run", json={}).status_code == 200
        assert _wait(c, rid)["status"] == "done"
        assert c.post(f"/api/runs/{rid}/edit", json={"artifact": "chapter:2", "instruction": "kürzer"}).status_code == 200
        assert c.get(f"/api/runs/{rid}/events").status_code == 200
        assert c.get("/api/runs/..%2F..%2Fetc/artifact/passwd").status_code == 404
        assert len(c.get("/api/runs").json()) == 1


async def test_experiment_grid_runs_and_resumes(tmp_path, monkeypatch):
    shutil.copytree(DATA, tmp_path / "data")
    plan = tmp_path / "plan.yaml"
    plan.write_text(f"""
name: t
output: {tmp_path / 'out'}
inputs: [{{path: "data/nl_storm.txt", kind: source}}, {{path: "data/nl_brieven.txt", kind: source}}]
conditions: {{full: {{preset: full}}, paraphrase: {{preset: paraphrase}}, flat: {{preset: flat}}}}
models: {{fake: {{models.default.name: fake/x}}}}
judge: {{model: fake/judge, instruments: [spec_recovery, dimension_fidelity, quality_pairwise], quality_baseline: flat}}
""")
    res = await run_experiment(plan)
    assert res["jobs"] == 6
    out = tmp_path / "out"
    rows = (out / "results.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 7
    header = rows[0].split(",")
    for col in ("usage.cost_usd", "usage.cost_usd_first_run", "timing.wall_seconds", "stage.draft.wall_seconds",
                "stage.extract.prompt_tokens", "stage.review.cost_usd"):
        assert col in header, col
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["failed"] == 0
    assert "judge.spec_recovery.mean" in summary["summary"]["full / fake"]
    assert "judge.quality.win" in summary["summary"]["full / fake"]
    mtime = (out / "runs" / "nl_storm--full--fake--r1" / "story.md").stat().st_mtime
    await run_experiment(plan)  # resume: nothing regenerated
    assert (out / "runs" / "nl_storm--full--fake--r1" / "story.md").stat().st_mtime == mtime
    report = Path(out / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Experiment: t") and "## Cost and time per stage" in report
    assert "| draft |" in report
    assert summary["summary"]["full / fake"]["stages"]["draft"]["wall_seconds"] >= 0


def test_web_batch_of_files_runs_through_the_queue(tmp_path):
    names = ["en_harbour.txt", "en_ledger.txt", "nl_storm.txt"]
    files = [("files", (n, (DATA / n).read_bytes(), "text/plain")) for n in names]
    with TestClient(create_app(tmp_path)) as c:
        assert c.get("/api/queue").json()["max_parallel"] == 1                     # the default
        assert c.put("/api/queue", json={"max_parallel": 0}).status_code == 400
        r = c.post("/api/runs", files=files, data={"preset": "full", "until": "spec",
                                                    "overrides": json.dumps({"models.default.name": "fake/w"})}).json()
        ids = r["ids"]
        assert len(ids) == 3 and r["batch"] and r["queued"] == ids[1:]          # one starts, two wait, in order
        listed = {x["id"]: x for x in c.get("/api/runs").json()}
        assert [listed[i]["queue_position"] for i in ids] == [None, 1, 2]
        assert {listed[i]["batch"] for i in ids} == {r["batch"]}
        assert [listed[i]["input_name"] for i in ids] == names
        assert listed[ids[2]]["status"] == "queued"
        c.post(f"/api/runs/{ids[2]}/cancel")                                       # take the last one out
        assert c.get(f"/api/runs/{ids[2]}").json()["status"] == "created"
        t0 = time.time()
        while time.time() - t0 < 60:
            st = [c.get(f"/api/runs/{i}").json() for i in ids[:2]]
            if all(not s["executing"] and s["status"] in ("done", "partial") for s in st):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the batch did not finish")
        assert c.get(f"/api/runs/{ids[2]}").json()["status"] == "created"         # never started
        assert c.get("/api/queue").json()["queued"] == []
        bad = c.post("/api/runs", files=[("files", ("a.txt", b"text", "text/plain")), ("files", ("b.txt", b" ", "text/plain"))],
                     data={"preset": "full"})
        assert bad.status_code == 400 and "b.txt" in bad.json()["detail"]
        assert len(c.get("/api/runs").json()) == 3                                 # nothing created for a bad batch
    from psalm_saga.store import RunStore

    RunStore(tmp_path / ids[2]).update_meta(status="queued")                       # as left by a server that stopped
    with TestClient(create_app(tmp_path)) as c:
        assert c.get(f"/api/runs/{ids[2]}").json()["status"] == "created"         # shown as not started


def test_web_preflight_settings_and_control(tmp_path):
    book = (DATA / "en_harbour.txt").read_text(encoding="utf-8")
    with TestClient(create_app(tmp_path)) as c:
        meta = c.get("/api/meta").json()
        assert meta["priorities"]["effects"] and meta["psalm_scale"]["scale"]["4"]
        chk = c.post("/api/check", json={"preset": "full", "overrides": {"models.default.name": "nonexistent/x"}}).json()
        assert not chk["ok"] and chk["problems"][0]["where"] == "models.default"
        rid = c.post("/api/runs", data={"text": book, "preset": "full",
                                        "overrides": json.dumps({"models.default.name": "nonexistent/x"})}).json()["id"]
        st = _wait(c, rid)
        assert st["status"] == "needs_attention"
        assert c.post(f"/api/runs/{rid}/control", json={"action": "pause"}).status_code == 409   # not executing
        r = c.put(f"/api/runs/{rid}/config", json={"overrides": {"models.default.name": "fake/w", "priorities": ["style"]}})
        assert r.status_code == 200 and r.json()["config"]["priorities"] == ["style"]
        assert c.post(f"/api/runs/{rid}/check").json()["ok"]
        c.post(f"/api/runs/{rid}/run", json={})
        assert _wait(c, rid)["status"] == "done"


async def test_experiment_validity_checks_and_per_condition_repeats(tmp_path):
    shutil.copytree(DATA, tmp_path / "data")
    plan = tmp_path / "plan.yaml"
    plan.write_text(f"""
name: v
output: {tmp_path / 'out'}
inputs: [{{path: "data/en_harbour.txt", kind: source}}, {{path: "data/en_ledger.txt", kind: source}}]
conditions: {{full: {{preset: full, repeats: 2}}, flat: {{preset: flat}}}}
models: {{fake: {{models.default.name: fake/x}}}}
overrides: {{judges.enabled: true, judges.model: fake/judge, judges.instruments: [psalm]}}
judge: {{model: fake/judge, check_models: [fake/judge2, fake/judge3], instruments: [psalm_check, psalm_anchor, alignment_anchor]}}
""")
    res = await run_experiment(plan)
    assert res["jobs"] == 2 * 2 + 2                                  # full twice per item, flat once
    out = tmp_path / "out"
    j = json.loads((out / "judgements.json").read_text(encoding="utf-8"))
    full1 = j["en_harbour--full--fake--r1"]
    assert set(full1["psalm_checks"]) == {"fake/judge2", "fake/judge3"} and "psalm_anchor" in full1 and full1["psalm_anchor"]["partner"] == "en_ledger"
    v = json.loads((out / "summary.json").read_text(encoding="utf-8"))["corpus"]["validity"]
    assert v["judge_agreement"]["judges"] == 3 and set(v["judge_agreement"]["pairwise"]) == {"fake/judge2", "fake/judge3"}
    assert v["judge_agreement"]["aspects"] > 0 and v["psalm_lower_anchor"]["pairs"] >= 1


def test_krippendorff_alpha():
    from psalm_saga.eval.validity import krippendorff_alpha_interval

    assert krippendorff_alpha_interval([(1, 1), (3, 3), (5, 5)]) == 1.0
    assert krippendorff_alpha_interval([(1, 5), (5, 1), (3, 3)]) < 0
    from psalm_saga.eval.validity import krippendorff_alpha_units

    # three coders with a missing value, checked against the `krippendorff` package (interval)
    units = [[1, 2, 1], [3, 3, None], [4, 5, 4], [2, 2, 3], [5, 4, 5]]
    assert krippendorff_alpha_units(units) == pytest.approx(0.8556, abs=1e-4)


def test_period_split_by_rule():
    from psalm_saga.experiments.runner import derive_period

    meta = {"a": {"year": "1850"}, "b": {"year": "1880"}, "c": {"year": "1900"}, "d": {"year": "1925"}, "e": {}}
    assert derive_period(meta) == 1890
    assert [meta[k].get("period") for k in "abcde"] == ["early", "early", "late", "late", None]
