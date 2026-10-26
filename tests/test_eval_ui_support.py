from fastapi.testclient import TestClient

from psalm_saga.eval.grading import BY_KEY, grade, suggest_fixes
from psalm_saga.pipeline import Pipeline
from psalm_saga.web.app import create_app
from tests.conftest import FAKE


def test_grades_and_fixes_follow_the_catalogue():
    assert grade(BY_KEY["span"], 7) == "good" and grade(BY_KEY["span"], 11) == "warn" and grade(BY_KEY["span"], 30) == "bad"
    assert grade(BY_KEY["length_ratio"], 1.05) == "good" and grade(BY_KEY["length_ratio"], 0.7) == "bad"
    assert grade(BY_KEY["jsd"], 0.3) == ""  # descriptive
    rep = {"leakage": {"ngram8_overlap": 0.02, "longest_copied_span_words": 30, "names_leaked": 0},
           "fidelity": {"stylometric_mean_rel_diff": 0.3,
                        "stylometrics": {"mean_sentence_words": {"source": 8, "synthetic": 20, "rel_diff": 0.6}}}}
    fixes = {f["id"]: f for f in suggest_fixes(rep)}
    assert fixes["leakage"]["rerun_from"] == "guard" and fixes["leakage"]["overrides"]["stages.guard.params.min_span"] == 8
    # style is fixed by the style-matching stage alone, without rewriting the content
    assert fixes["style"]["rerun_from"] == "conform" and fixes["style"]["overrides"]["stages.conform.params.rounds"] > 2


def test_evaluation_explains_gaps_and_fix_endpoint(tmp_path, nl_text):
    import asyncio
    import time

    p = Pipeline.create("full", runs_dir=tmp_path, source=nl_text, overrides=FAKE, run_id="ev")
    asyncio.run(p.run())
    ev = p.store.read_json("evaluation.json")
    assert ev["grades"] and isinstance(ev["not_measurable"], dict)
    for key in ("salience", "presence", "jaccard", "chapter_r", "kg_characters", "retention"):
        assert key in ev["grades"] or key in ev["not_measurable"], key
    with TestClient(create_app(tmp_path)) as c:
        meta = c.get("/api/meta").json()["evaluation"]
        assert {"form", "style", "structure", "characters", "content", "distance"} == set(meta["groups"])
        assert c.post("/api/runs/ev/fix", json={"id": "nope"}).status_code == 404
        assert ev["fixes"], "the offline model's text should need at least one fix"
        fx = ev["fixes"][0]
        r = c.post("/api/runs/ev/fix", json={"id": fx["id"]})
        assert r.status_code == 200 and r.json()["id"] == "ev-v2"      # a new version, not an overwrite
        for _ in range(300):
            st = c.get("/api/runs/ev-v2").json()
            if not st["executing"]:
                break
            time.sleep(0.1)
        assert st["status"] == "done" and st["meta"]["parent"] == "ev" and st["meta"]["version"] == 2
        assert st["meta"]["evaluation_guided_fixes"][-1]["fixes"] == [fx["id"]]
        for k, v in fx["overrides"].items():
            cur = st["meta"]["config"]
            for part in k.split("."):
                cur = cur[part]
            assert cur == v
        orig = c.get("/api/runs/ev").json()["meta"]
        assert not orig.get("evaluation_guided_fixes") and not orig.get("parent")   # the original is untouched
        vers = c.get("/api/runs/ev-v2/versions").json()
        assert [f["version"] for f in vers["family"]] == [1, 2] and "comparison" in vers


def test_versions_replace_old_fix_instructions(tmp_path):
    import json

    from psalm_saga.fixes import make_version

    run = tmp_path / "r"
    run.mkdir()
    old_fix = {"stages.draft.params.extra_instruction": "The previous draft drifted. Old numbers."}
    cfg = {"stages": {"draft": {"params": {"extra_instruction": "My own note.\n\nThe previous draft drifted. Old numbers.",
                                           "fix_instruction": "stale"}}, "plan": {"params": {}}},
           "transform": {"notes": ""}}
    (run / "run.json").write_text(json.dumps({"id": "r", "config": cfg, "evaluation_guided_fixes": [{"overrides": old_fix}]}))
    nid, frm, _ = make_version(tmp_path, "r", [{"id": "length", "rerun_from": "draft",
                                               "overrides": {"stages.draft.params.fix_instruction": "Shorter."}}])
    m = json.loads((tmp_path / nid / "run.json").read_text())
    p = m["config"]["stages"]["draft"]["params"]
    assert nid == "r-v2" and frm == "draft"
    assert p["extra_instruction"] == "My own note." and p["fix_instruction"] == "Shorter."   # user note kept, old fix gone
