"""Re-invent and replace: the design changes particulars (re-invent) or is invented anew (replace),
source-side measures are not graded where the policy changes their dimension, and the PSALM
expectations follow the policy."""

import json
from pathlib import Path

from psalm_saga.artifacts import ChapterSummary, EventNote, SceneNote
from psalm_saga.eval.grading import grades, policy_exclusions
from psalm_saga.eval.kg_align import mark_policy
from psalm_saga.eval.run_judges import EXPECTED
from psalm_saga.pipeline import Pipeline
from psalm_saga.stages.transform import _too_close
from tests.conftest import FAKE

DATA = Path(__file__).parent / "data"
ALL = ("writing_style", "narrative_voice", "character", "plot_structure", "scene_sequence", "world_building")


def _all(policy: str) -> list[str]:
    return [f"transform.policy.{d}={policy}" for d in ALL]


async def test_replace_invents_a_new_story_without_seeing_the_source_values(runs):
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, *_all("regenerate")], run_id="repl")
    await p.run(until="transform")
    assert p.store.read_json("transform_log.json")["skeleton"] == "new story"
    calls = [json.loads(f.read_text(encoding="utf-8")) for f in p.store.glob("calls/*.json")]
    dims = [c for c in calls if c["tag"].startswith("transform:") and c["tag"].split(":")[1] in ALL]
    assert dims and all("Original specification of" not in json.dumps(c["messages"]) for c in dims)
    ents = [c for c in calls if c["tag"] == "transform:entities"]
    assert ents and "(replaced: invent)" in json.dumps(ents[0]["messages"])
    assert any(c["tag"] == "transform:new_story" for c in calls)


async def test_reinvent_rechecks_particulars(runs):
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "en_harbour.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, *_all("abstract")], run_id="abs")
    await p.run(until="transform")
    log = p.store.read_json("transform_log.json")
    assert log["skeleton"] in ("re-invented", "renamed")


def test_too_close_flags_kept_particulars():
    old = ChapterSummary(index=1, summary="", scenes=[SceneNote(summary="Jim trains the frog to jump and catch flies")],
                         events=[EventNote(description="A stranger fills the frog with quail shot so it cannot jump")])
    same = old.model_copy(deep=True)
    new = ChapterSummary(index=1, summary="", scenes=[SceneNote(summary="Jim drills his rooster to crow on cue at dawn")],
                         events=[EventNote(description="A rival soaks the rooster's feed in rum so it sleeps through the call")])
    assert len(_too_close(old, same, {"jim"})) == 2 and not _too_close(old, new, {"jim"})


def test_measures_of_a_changed_dimension_are_not_graded():
    ex = policy_exclusions({d: "regenerate" for d in ALL})
    assert {"style_drift", "fw_cosine", "sentence_overlap", "salience", "scenes", "judge_content"} <= set(ex)
    assert "kg_events" not in ex and "ngram8" not in ex
    ex_abs = policy_exclusions({d: "abstract" for d in ALL})
    assert "salience" not in ex_abs and "style_drift" in ex_abs
    report = {"fidelity": {"stylometric_mean_rel_diff": 0.4}, "not_measurable": ex, "leakage": {"ngram8_overlap": 0.0}}
    g = grades(report)
    assert "style_drift" not in g and "ngram8" in g


def test_expected_ranges_and_policy_marks():
    assert EXPECTED["abstract"]["function"] == [4, 5] and EXPECTED["abstract"]["expression"] == [1, 2]
    assert EXPECTED["regenerate"]["function"] == [1, 2] and EXPECTED["regenerate"]["expression"] == [1, 2]
    cmp = {"nodes": [{"id": "v1.1", "type": "event", "status": "kept"}, {"id": "e1", "type": "character", "status": "kept"}],
           "edges": [{"type": "causes", "status": "kept"}]}
    out = mark_policy(cmp, {"plot_structure": "abstract", "character": "preserve"})
    st = {n["id"]: n["status"] for n in out["nodes"]}
    assert st == {"v1.1": "changed", "e1": "kept"} and out["edges"][0]["status"] == "changed"
