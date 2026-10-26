import json

from psalm_saga.artifacts import ChapterReview, Issue
from psalm_saga.pipeline import Pipeline
from psalm_saga.stages.review import Review
from tests.conftest import FAKE


def _issue(origin, severity="major"):
    return Issue(severity=severity, origin=origin, commitment=f"{origin} commitment", evidence="e", fix="f")


async def test_issues_are_fixed_where_they_originate(runs, nl_text, monkeypatch):
    calls: dict[int, int] = {}

    async def scripted(self, ctx, spec_txt, plan_txt, cast, text, index, r, checklist=None):
        n = calls[index] = calls.get(index, 0) + 1
        issues = []
        if index == 1 and n == 1:
            issues = [_issue("plan")]            # plan at fault -> re-plan + redraft
        elif index == 2:
            issues = [_issue("spec", "blocker")]  # spec at fault, every time -> one backtrack, then recorded
        elif index == 3 and n == 1:
            issues = [_issue("prose")]           # prose at fault -> paragraph repair
        return ChapterReview(index=index, issues=issues)

    monkeypatch.setattr(Review, "check", scripted)
    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="route")
    await p.run()
    st = p.store
    assert st.meta()["status"] == "done"
    events = [json.loads(line) for line in st.read_text("events.jsonl").splitlines()]
    back = [e for e in events if e["type"] == "backtrack"]
    assert len(back) == 1 and back[0]["to_stage"] == "plan"
    log = st.read_json("backtracks.json")
    assert len(log) == 1 and log[0]["amended"] == ["spec"] and log[0]["issues"][0]["chapter"] == 2
    # After the backtrack the run re-planned and re-reviewed; the remaining spec issue is recorded, not hidden.
    r2 = st.read_json("reviews/ch_002.json")
    assert r2["upstream"] and r2["upstream"][0]["origin"] == "spec"
    assert any(e["type"] == "warning" and "no backtracks left" in e.get("message", "") for e in events)
    # Chapter 1 was re-planned (in the first pass, before the backtrack wiped the plan).
    actions = [e for e in events if e["type"] == "llm_call" and str(e.get("tag", "")).startswith("replan:ch1")]
    assert actions
    tags = [str(e.get("tag", "")) for e in events if e["type"] == "llm_call"]
    assert any(t.startswith("repair:ch3") for t in tags)          # prose issue -> repair
    assert not any(t.startswith(("repair:ch1", "repair:ch2")) for t in tags)  # others were not "repaired" in prose


async def test_replan_replaces_the_chapter_plan(runs, nl_text, monkeypatch):
    calls: dict[int, int] = {}

    async def scripted(self, ctx, spec_txt, plan_txt, cast, text, index, r, checklist=None):
        n = calls[index] = calls.get(index, 0) + 1
        return ChapterReview(index=index, issues=[_issue("plan")] if index == 1 and n == 1 else [])

    monkeypatch.setattr(Review, "check", scripted)
    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="replan")
    await p.run()
    r1 = p.store.read_json("reviews/ch_001.json")
    assert [h["action"] for h in r1["rounds"]] == ["review", "replan"] and r1["rounds"][1]["kept"]
    assert r1["replanned"] and not p.store.exists("backtracks.json")
