import json
import shutil
import time
from pathlib import Path

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
