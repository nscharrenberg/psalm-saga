import json

import pytest

from psalm_saga import Saga
from psalm_saga.config import preset_names
from psalm_saga.pipeline import Pipeline
from tests.conftest import FAKE, dutch_novel


async def _run(runs, preset="full", overrides=(), **inp) -> Pipeline:
    p = Pipeline.create(preset, runs_dir=runs, overrides=[*FAKE, *overrides], **inp)
    await p.run()
    return p


@pytest.mark.parametrize("preset", preset_names())
async def test_every_preset_runs_on_source(runs, nl_text, preset):
    from psalm_saga.config import load_config

    roles = [f"models.{r}.name=fake/test" for r in load_config(preset).models]  # e.g. `fast` routes extraction elsewhere
    p = await _run(runs, preset, roles, source=nl_text)
    assert p.store.meta()["status"] == "done"
    ev = p.store.read_json("evaluation.json")
    assert ev["language"]["expected"] == "nl" and ev["language"]["ok"]
    assert p.store.exists("story.md")


async def test_full_source_run_keeps_structure_and_language(runs, nl_text):
    p = await _run(runs, source=nl_text)
    story = p.store.read_text("story.md")
    assert "## Hoofdstuk 1" in story and "Chapter" not in story
    ev = p.store.read_json("evaluation.json")
    assert ev["fidelity"]["chapter_count"]["equal"]
    assert ev["leakage"]["longest_copied_span_words"] < 10
    spec = p.store.read_json("spec.json")
    pol = {d["dimension"]: d["policy"] for d in spec["dimensions"]}
    assert pol["character"] == "abstract" and pol["writing_style"] == "preserve"
    # Clean-room boundary: nothing after transform received the source text.
    events = p.store.events()
    tags = [e.get("tag", "") for e in events if e["type"] == "llm_call"]
    assert any(t.startswith("draft:") for t in tags)


async def test_premise_mode_follows_premise_language(runs):
    from pathlib import Path

    premise = (Path(__file__).parent.parent / "examples" / "gothic_vrouw_holle.md").read_text(encoding="utf-8")
    p = await _run(runs, premise=premise, overrides=["length.target_words=1200"])
    assert p.language() == "nl"
    ev = p.store.read_json("evaluation.json")
    assert ev["language"]["detected"] == "nl"
    assert 0.8 < ev["length"]["ratio"] < 1.25


async def test_explicit_output_language(runs, nl_text):
    p = await _run(runs, "no_review", source=nl_text, overrides=["language.output=de"])
    assert p.store.read_json("evaluation.json")["language"]["detected"] == "de"
    assert "## Kapitel 1" in p.store.read_text("story.md")


async def test_wrong_language_is_detected_and_retried(runs, nl_text):
    p = await _run(runs, "no_review", source=nl_text, overrides=["models.default.extra.fake_wrong_language=en"])
    mism = [e for e in p.store.events() if e["type"] == "language_mismatch"]
    assert mism, "expected the first (English) attempts to be caught"
    assert p.store.read_json("evaluation.json")["language"]["chapters_off_language"] == []


async def test_partial_spec_template_is_completed(runs):
    spec = {"language": "en", "title": "The Lamp", "logline": "A keeper finds a letter.", "target_words": 1500,
            "chapters": 2, "dimensions": [{"dimension": "narrative_voice", "summary": "first person",
                                           "items": [{"key": "point_of_view", "value": "first person, retrospective"}]}]}
    p = await _run(runs, spec=spec)
    out = p.store.read_json("spec.json")
    assert out["dimensions"][0]["dimension"] == "narrative_voice"
    assert out["dimensions"][0]["items"][0]["value"] == "first person, retrospective"  # template kept verbatim
    assert len(out["dimensions"]) == 6 and out["title"] == "The Lamp"


async def test_resume_after_crash_reuses_finished_work(runs, nl_text, monkeypatch):
    from psalm_saga.stages import draft as draft_mod

    original = draft_mod.write_unit
    calls = {"n": 0}

    async def flaky(*a, **kw):  # crash while drafting the second chapter
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated provider outage")
        return await original(*a, **kw)

    monkeypatch.setattr(draft_mod, "write_unit", flaky)
    p = Pipeline.create("no_review", runs_dir=runs, source=nl_text, overrides=[*FAKE, "limits.max_parallel_chapters=1"])
    with pytest.raises(RuntimeError):
        await p.run()
    assert p.store.meta()["status"] == "failed"
    assert p.store.exists("chapters/ch_001.json") and not p.store.exists("chapters/ch_002.json")
    n_events = len(p.store.events())

    q = Pipeline.open(p.store.root)
    await q.run()
    assert q.store.meta()["status"] == "done"
    new = q.store.events()[n_events:]
    started = [e["stage"] for e in new if e["type"] == "stage_started"]
    assert started[0] == "draft", "finished stages must not rerun"
    redrafted = {e["tag"] for e in new if e["type"] == "llm_call" and e.get("tag", "").startswith("draft:")}
    assert not any(t.startswith("draft:ch1") for t in redrafted), "finished chapters must not be redrafted"


async def test_rerun_from_plan_only_redoes_downstream(runs, nl_text):
    p = await _run(runs, "no_review", source=nl_text)
    n = len(p.store.events())
    await p.run(rerun_from="plan")
    later = [e for e in p.store.events()[n:] if e["type"] == "stage_started"]
    assert [e["stage"] for e in later] == ["plan", "draft", "conform", "guard", "assemble", "recover", "evaluate"]


def test_sdk_edit_invalidates_downstream(runs, nl_text):
    saga = Saga("no_review", overrides=FAKE, runs_dir=runs)
    run = saga.synthesize(nl_text)
    assert run.story
    run.edit("spec", "Make the narrator intrude with ironic asides.")
    st = {s["name"]: s["done"] for s in run.status()["stages"]}
    assert st["transform"] and not st["plan"] and not st["draft"]
    run.run()
    assert run.story and run.status()["status"] == "done"
    run.put("chapter:1", "Nieuwe tekst van het eerste hoofdstuk, met de hand geschreven.")
    run.run()
    assert "met de hand geschreven" in run.story


async def test_hundred_thousand_word_novel_stays_in_bounded_context(runs):
    book = dutch_novel(chapters=30, words_per_chapter=3400)
    assert len(book.split()) > 100_000
    p = Pipeline.create("full", runs_dir=runs, source=book, overrides=FAKE)
    await p.run()
    events = p.store.events()
    calls = [e for e in events if e["type"] == "llm_call"]
    assert max(e["prompt_tokens"] for e in calls) < 20_000, "no call may carry the whole book"
    ev = p.store.read_json("evaluation.json")
    assert ev["fidelity"]["chapter_count"] == {"source": 30, "synthetic": 30, "equal": True}
    assert 0.85 < ev["length"]["ratio"] < 1.2
    assert ev["language"]["ok"]
    assert len(p.store.glob("notes/chunk_*.json")) == 30
    plan = json.loads(p.store.read_text("plan.json"))
    budgets = [c["target_words"] for c in plan["chapters"]]
    assert abs(sum(budgets) - ev["length"]["target"]) / ev["length"]["target"] < 0.05


async def test_rate_limits_do_not_fail_a_run(runs, nl_text):
    p = await _run(runs, "no_review", source=nl_text, overrides=["models.default.extra.fake_rate_limit_every=3"])
    assert p.store.meta()["status"] == "done"
    assert p.store.meta()["usage"]["retries"] > 0
