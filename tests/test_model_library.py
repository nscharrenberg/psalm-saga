"""The model library: a model is described once and chosen by name for every task."""

from pathlib import Path

import pytest

from psalm_saga import model_library as ml
from psalm_saga.config import load_config
from psalm_saga.pipeline import Pipeline

SRC = (Path(__file__).parent / "data" / "en_harbour.txt").read_text(encoding="utf-8")


def test_choosing_a_library_model_copies_its_settings_and_keeps_the_task_temperature():
    c = load_config("full", ["models.default.use=gemma-4-e4b", "models.default.temperature=0.5"])
    m = c.models["default"]
    assert (m.use, m.name, m.extra["api_base"], m.context_window, m.max_output_tokens, m.max_concurrency) == \
        ("gemma-4-e4b", "ollama_chat/gemma4:e4b", "http://localhost:11434", 131072, 8192, 1)
    assert m.temperature == 0.5                       # the task's, not the model's


def test_a_step_on_another_model_does_not_inherit_the_writers_endpoint():
    c = load_config("full", ["models.default.use=gemma-4-e4b", "models.extract.use=claude-sonnet-5-5"])
    assert c.models["extract"].name == "anthropic/claude-sonnet-5-5" and "api_base" not in c.models["extract"].extra
    c = load_config("fast", ["models.default.use=gemma-4-e4b"])   # the preset's own analysis model stays its own
    assert c.models["extract"].name.startswith("anthropic/") and c.models["extract"].use is None
    assert "api_base" not in c.models["extract"].extra


def test_judges_and_panel_by_name():
    c = load_config("full", ["judges.enabled=true", "judges.model=claude-sonnet-5-5",
                             'judges.panel=["gpt-6-luna", "qwen3.5-397b", "openai/other"]'])
    j = c.judge_model()
    assert j.name == "anthropic/claude-sonnet-5-5" and j.temperature == 0.0
    panel = c.panel_models()
    assert [p.name for p in panel] == ["openai/gpt-6-luna", "hosted_vllm/Qwen/Qwen3.5-397B-A17B", "openai/other"]
    assert panel[1].extra["api_base"] == "http://localhost:8000/v1" and "api_base" not in panel[0].extra


def test_a_run_keeps_the_model_settings_it_was_made_with(runs):
    ml.save("mine", {"label": "Mine", "name": "fake/mine", "max_output_tokens": 1234})
    p = Pipeline.create("full", runs_dir=runs, source=SRC, overrides=["models.default.use=mine"], run_id="snap")
    assert p.config.models["default"].max_output_tokens == 1234
    ml.save("mine", {"label": "Mine", "name": "fake/mine", "max_output_tokens": 999})
    assert Pipeline.open(p.store.root).config.models["default"].max_output_tokens == 1234        # unchanged
    assert Pipeline.open(p.store.root, overrides=["models.default.use=mine"]).config.models["default"].max_output_tokens == 999


def test_unknown_library_name_is_a_clear_error():
    with pytest.raises(ValueError, match="no model called 'nope'"):
        load_config("full", ["models.default.use=nope"])


def test_library_entries_are_validated_and_editable():
    with pytest.raises(ValueError):
        ml.save("bad name!", {"name": "x/y"})
    with pytest.raises(ValueError):
        ml.save("ok", {"label": "no id"})
    e = ml.save("gemma-4-e4b", {**ml.BUILTIN["gemma-4-e4b"], "api_base": "http://gpu-box:11434"})
    assert e["source"] == "edited built-in" and ml.get("gemma-4-e4b")["api_base"] == "http://gpu-box:11434"
    ml.delete("gemma-4-e4b")
    assert ml.get("gemma-4-e4b")["api_base"] == "http://localhost:11434"


async def test_a_full_run_with_library_models_and_judges(runs):
    p = Pipeline.create("full", runs_dir=runs, source=SRC, run_id="lib",
                        overrides=["models.default.use=offline-test", "judges.enabled=true", "judges.model=offline-test",
                                   'judges.panel=["offline-test"]'])
    await p.run()
    jd = p.store.read_json("evaluation.json")["judges"]
    assert jd["use"] == "offline-test" and jd["per_judge"][1]["model"] == "fake/demo"


def test_web_model_library(tmp_path):
    from fastapi.testclient import TestClient

    from psalm_saga.web.app import create_app

    c = TestClient(create_app(tmp_path / "runs", experiments_dir=tmp_path / "exp"))
    ms = c.get("/api/models").json()["models"]
    assert {"mistral-large-4", "gemma-4-e4b", "offline-test"} <= {m["alias"] for m in ms}
    assert next(m for m in ms if m["alias"] == "offline-test")["key_ready"] is True
    r = c.put("/api/models/my-vllm", json={"entry": {"label": "My vLLM", "name": "hosted_vllm/x", "api_base": "http://h:1/v1"}})
    assert r.status_code == 200 and r.json()["source"] == "yours"
    assert c.put("/api/models/x", json={"entry": {"label": "no id"}}).status_code == 400
    t = c.post("/api/models/offline-test/test").json()
    assert t["ok"] is True
    assert c.delete("/api/models/my-vllm").json()["ok"]
