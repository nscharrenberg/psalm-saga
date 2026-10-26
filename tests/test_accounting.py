"""Token, cost and time accounting: per stage, across resumes, with price overrides."""

import pytest

from psalm_saga.config import ModelConfig
from psalm_saga.llm import LLM
from psalm_saga.pipeline import Pipeline
from tests.conftest import FAKE

PRICED = [*FAKE, "models.default.input_cost_per_mtok=3", "models.default.output_cost_per_mtok=15"]


async def test_per_stage_usage_and_timing(runs, nl_text):
    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=PRICED)
    await p.run()
    meta = p.store.meta()
    u, t = meta["usage"], meta["timing"]
    by = u["by_stage"]
    assert {"extract", "spec", "transform", "plan", "draft", "review"} <= set(by)
    # Stage breakdown adds up to the totals.
    for k in ("calls", "prompt_tokens", "completion_tokens"):
        assert sum(b[k] for b in by.values()) == u[k]
    assert sum(b["cost_usd"] for b in by.values()) == pytest.approx(u["cost_usd"], rel=1e-6)
    # Configured prices are applied: $3 / $15 per million tokens.
    expected = (u["prompt_tokens"] * 3 + u["completion_tokens"] * 15) / 1e6
    assert u["cost_usd"] == pytest.approx(expected, rel=1e-6) and u["unpriced_calls"] == 0
    # Wall clock per stage, and in total.
    assert t["invocations"] == 1 and t["wall_seconds"] > 0
    assert all(t["stages"][s]["completed"] == 1 for s in ("extract", "plan", "draft", "evaluate"))
    assert sum(s["wall_seconds"] for s in t["stages"].values()) <= t["wall_seconds"] + 0.01
    finished = [e for e in p.store.events() if e["type"] == "stage_finished" and e["stage"] == "draft"]
    assert finished[0]["calls"] == by["draft"]["calls"]
    ev = p.store.read_json("evaluation.json")
    assert ev["usage"]["calls"] == u["calls"] and "stages" in ev["timing"]


async def test_baseline_calls_are_attributed_to_the_running_stage(runs, nl_text):
    p = Pipeline.create("agents_room", runs_dir=runs, source=nl_text, overrides=FAKE)
    await p.run()
    by = p.store.meta()["usage"]["by_stage"]
    assert "agents_room" not in by and by["draft"]["calls"] == 9  # 4 planners + 5 writers
    assert "agents_room:climax" in p.store.meta()["usage"]["by_tag"]


async def test_accounting_accumulates_across_resume_and_failure(runs, nl_text, monkeypatch):
    from psalm_saga.stages import draft as draft_mod

    original, n = draft_mod.write_unit, {"calls": 0}

    async def flaky(*a, **kw):
        n["calls"] += 1
        if n["calls"] == 2:
            raise RuntimeError("simulated outage")
        return await original(*a, **kw)

    monkeypatch.setattr(draft_mod, "write_unit", flaky)
    p = Pipeline.create("no_review", runs_dir=runs, source=nl_text,
                        overrides=[*PRICED, "limits.max_parallel_chapters=1", "cache=false"])
    with pytest.raises(RuntimeError):
        await p.run()
    first = p.store.meta()
    assert first["status"] == "failed" and first["usage"]["calls"] > 0
    d0 = first["timing"]["stages"]["draft"]
    assert d0["runs"] == 1 and d0["completed"] == 0 and d0["wall_seconds"] > 0  # time of the failed attempt is kept

    q = Pipeline.open(p.store.root)
    await q.run()
    second = q.store.meta()
    assert second["timing"]["invocations"] == 2
    assert second["timing"]["wall_seconds"] >= first["timing"]["wall_seconds"]
    assert second["seconds"] == pytest.approx(second["timing"]["wall_seconds"], abs=0.1)
    d = second["timing"]["stages"]["draft"]
    assert d["runs"] == 2 and d["completed"] == 1 and d["wall_seconds"] >= d["last_wall_seconds"]
    assert second["timing"]["stages"]["extract"]["runs"] == 1  # finished stages are not re-timed
    assert second["usage"]["calls"] > first["usage"]["calls"]
    assert second["usage"]["cost_usd"] > first["usage"]["cost_usd"]


async def test_cache_hits_record_what_they_would_have_cost(runs, nl_text):
    a = Pipeline.create("no_review", runs_dir=runs, source=nl_text, overrides=PRICED, run_id="a")
    await a.run()
    b = Pipeline.create("no_review", runs_dir=runs, source=nl_text, overrides=PRICED, run_id="b")
    await b.run()
    ua, ub = a.store.meta()["usage"], b.store.meta()["usage"]
    assert ub["cost_usd"] == 0 and ub["cached_calls"] == ub["calls"]
    assert ub["replayed_cost_usd"] == pytest.approx(ua["cost_usd"], rel=1e-6)
    assert ub["replayed_prompt_tokens"] == ua["prompt_tokens"]


def test_cost_resolution():
    # explicit prices, with a cheaper cached-input rate
    mc = ModelConfig(name="hosted_vllm/llama", input_cost_per_mtok=2, output_cost_per_mtok=6, cached_input_cost_per_mtok=0.5)
    assert LLM._cost(mc, 1_000_000, 1_000_000, cache_read=400_000) == pytest.approx(0.6 * 2 + 0.4 * 0.5 + 6)
    # unknown, unpriced model -> None (reported as unpriced, not silently $0)
    assert LLM._cost(ModelConfig(name="hosted_vllm/some-local-model"), 1000, 1000) is None
    assert LLM._cost(ModelConfig(name="fake/x"), 1000, 1000) == 0.0
