import asyncio
import time

import pytest
from pydantic import BaseModel

from psalm_saga.config import ModelConfig, PipelineConfig
from psalm_saga.llm import LLM, BudgetExceeded, LLMError, Part
from psalm_saga.llm.limiter import LimiterRegistry, ModelLimiter, retry_after_seconds


class Thing(BaseModel):
    name: str
    count: int


def make(tmp_path=None, **mc) -> LLM:
    cfg = PipelineConfig(models={"default": ModelConfig(name="fake/t", **mc)})
    return LLM(cfg, cache_dir=tmp_path, limiters=LimiterRegistry())


async def test_text_and_json():
    llm = make()
    txt = await llm.text("draft", "sys", [Part("write")], hints={"target_words": 120, "language": "nl"})
    assert 100 < len(txt.split()) < 140
    t = await llm.json("plan", "sys", [Part("give")], Thing)
    assert isinstance(t, Thing)


async def test_rate_limit_retry_honours_retry_after():
    events = []
    llm = make(extra={"fake_rate_limit_every": 2})
    llm.on_event = events.append
    for _ in range(4):
        await llm.text("x", "s", [Part(f"p{_}")], hints={"target_words": 10})
    retries = [e for e in events if e["type"] == "llm_retry"]
    assert retries and all(e["wait_s"] < 1.0 for e in retries)  # used the 0.05s hint, not a blind backoff
    assert llm.usage.retries == len(retries)


async def test_timeout_is_retried():
    llm = make(timeout_s=0.2, extra={"fake_hang_every": 1}, max_retries=1)
    t0 = time.monotonic()
    with pytest.raises(LLMError, match="TimeoutError"):
        await llm.text("x", "s", [Part("p")])
    assert time.monotonic() - t0 < 10


async def test_invalid_json_is_repaired():
    events = []
    llm = make(extra={"fake_bad_json_every": 1})
    llm.on_event = events.append
    with pytest.raises(LLMError):  # every call broken -> gives up after the repair rounds
        await llm.json("x", "s", [Part("p")], Thing, repairs=1)
    assert sum(e["type"] == "llm_repair" for e in events) == 2

    flaky = make(extra={"fake_bad_json_every": 2})
    await flaky.text("x", "s", [Part("warm-up")])  # call 1
    out = await flaky.json("x", "s", [Part("p")], Thing)  # call 2 truncated JSON -> repair call 3 succeeds
    assert isinstance(out, Thing) and flaky._fake.calls == 3


async def test_disk_cache_makes_reruns_free(tmp_path):
    a = make(tmp_path)
    t1 = await a.text("x", "s", [Part("same prompt")])
    b = make(tmp_path)
    t2 = await b.text("x", "s", [Part("same prompt")])
    assert t1 == t2 and b.usage.cached_calls == 1 and b._fake.calls == 0


async def test_budget_cap():
    llm = make()
    llm.config.limits.max_cost_usd = 0.0
    with pytest.raises(BudgetExceeded):
        await llm.text("x", "s", [Part("p")])


async def test_shared_cooldown_blocks_other_callers():
    lim = ModelLimiter(max_concurrency=4)
    lim.penalize(0.3)
    t0 = time.monotonic()
    await asyncio.gather(*(lim.acquire(10) for _ in range(3)))
    assert time.monotonic() - t0 >= 0.29
    for _ in range(3):
        lim.release()


async def test_rpm_bucket_paces_requests():
    lim = ModelLimiter(max_concurrency=10, rpm=600)  # 10/s, burst capacity 600 — drain it first
    lim._rpm.tokens = 0
    t0 = time.monotonic()
    for _ in range(3):
        await lim.acquire(1)
        lim.release()
    assert time.monotonic() - t0 >= 0.25


def test_retry_after_parsing():
    assert retry_after_seconds(Exception("Please try again in 3.608s.")) == pytest.approx(3.608)
    assert retry_after_seconds(Exception("retry after 250ms")) == pytest.approx(0.25)
    assert retry_after_seconds(Exception("boom")) is None


def test_anthropic_cache_markers():
    cfg = PipelineConfig(models={"default": ModelConfig(name="anthropic/claude-sonnet-5-5")})
    msgs = LLM(cfg)._messages("x", "sys", [Part("bible", cache=True), Part("task")])
    assert msgs[1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in msgs[1]["content"][1]
    cfg2 = PipelineConfig(models={"default": ModelConfig(name="openai/gpt-5.5")})
    assert isinstance(LLM(cfg2)._messages("x", "sys", [Part("a", cache=True), Part("b")])[1]["content"], str)


async def test_all_reasoning_no_answer_is_answered_from_the_models_own_notes():
    events = []
    llm = make(extra={"reasoning_effort": "medium", "fake_overthink_unless_told": True})
    llm.on_event = events.append
    out = await llm.json("x", "s", [Part("give")], Thing)
    assert isinstance(out, Thing)
    retries = [e for e in events if e["type"] == "llm_retry"]
    assert len(retries) == 1 and "from its own reasoning so far" in retries[0]["error"] and "'low'" in retries[0]["error"]
    assert llm.export_behaviour()["fake/t"]["effort"] == "low"


async def test_then_without_a_limit_of_our_own_then_a_clear_error():
    events = []
    llm = make(extra={"fake_overthink_below": 30000}, max_output_tokens=8000)
    llm.on_event = events.append
    txt = await llm.text("x", "s", [Part("write")], hints={"target_words": 50})
    assert txt and any("no output limit" in e.get("error", "") for e in events)
    stuck = make(extra={"fake_overthink": [None, "low"]})
    with pytest.raises(LLMError, match="kept reasoning without giving an answer"):
        await stuck.text("x", "s", [Part("write")], hints={"target_words": 50})


async def test_an_empty_answer_is_never_continued_or_cached(tmp_path):
    llm = make(tmp_path, extra={"fake_overthink": [None, "low"]})
    with pytest.raises(LLMError):
        await llm.text("x", "s", [Part("write")], hints={"target_words": 50})
    assert not list(tmp_path.rglob("*.json"))                 # nothing replayable was kept


async def test_the_reasoning_a_model_needed_sets_the_room_for_later_calls():
    llm = make(extra={"fake_reasoning_tokens": 20000}, reasoning=True, reasoning_headroom=8000)
    await llm.text("x", "s", [Part("one")], hints={"target_words": 50})
    mc = llm.config.models["default"]
    assert llm.headroom(mc) == 25000 and llm.allowance(mc, 1000) >= 26000
    b = llm.export_behaviour()
    fresh = make()
    fresh.load_behaviour(b)                                    # e.g. after resuming the run
    assert fresh.headroom(fresh.config.models["default"]) == 25000


def test_no_limit_of_our_own_stays_within_the_budget():
    cfg = PipelineConfig(models={"default": ModelConfig(name="fake/t", max_output_tokens=0, output_cost_per_mtok=10.0)})
    cfg.limits.max_cost_usd = 0.5
    llm = LLM(cfg, limiters=LimiterRegistry())
    assert llm.allowance(cfg.models["default"], None) == 50000   # $0.50 at $10 per million output tokens
    cfg.limits.max_cost_usd = None
    assert LLM(cfg, limiters=LimiterRegistry()).allowance(cfg.models["default"], None) == 0   # no limit sent at all


def test_reasoning_settings_in_the_providers_form():
    from psalm_saga.llm.client import _reasoning_params

    kw = {"reasoning_effort": "medium"}
    _reasoning_params(ModelConfig(name="openrouter/google/gemma-4-26b-a4b-it"), kw)
    assert kw == {"extra_body": {"reasoning": {"effort": "medium"}}}
    kw = {"reasoning_effort": "medium"}
    _reasoning_params(ModelConfig(name="openrouter/google/gemma-4-26b-a4b-it", reasoning_max_tokens=3000), kw)
    assert kw["extra_body"]["reasoning"] == {"max_tokens": 3000}
    kw = {"reasoning_effort": "none"}
    _reasoning_params(ModelConfig(name="openrouter/x/y", reasoning_max_tokens=3000), kw)
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    kw = {}
    _reasoning_params(ModelConfig(name="anthropic/claude-sonnet-5-5", reasoning_max_tokens=2000), kw)
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 2000}
    kw = {"reasoning_effort": "high"}
    _reasoning_params(ModelConfig(name="openai/gpt-x"), kw)
    assert kw == {"reasoning_effort": "high"}
