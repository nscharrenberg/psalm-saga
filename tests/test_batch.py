from pathlib import Path

import pytest

import psalm_saga.batch as batch_module
from psalm_saga.config import Settings  # type: ignore[import-untyped]
from psalm_saga.dimensions import (  # type: ignore[import-untyped]
    DivergenceIntensity,
    DivergencePlan,
    GenerationMode,
    LengthTier,
    StoryBible,
)


class _FakeOrchestrator:
    def invoke(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {}


class _FakeCheckpointerCtx:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return object()

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False


class _FakeSqliteSaver:
    @staticmethod
    def from_conn_string(_path):  # type: ignore[no-untyped-def]
        return _FakeCheckpointerCtx()


def test_run_dataset_item_forwards_length_tier_to_init_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    plan = DivergencePlan.uniform(DivergenceIntensity.CLOSE)

    def fake_init_session(settings, mode, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        session_dir = tmp_path / "item-session"
        session_dir.mkdir(exist_ok=True)
        bible = StoryBible(mode=GenerationMode.FROM_SOURCE, divergence_plan=plan)
        (session_dir / "story_bible.json").write_text(bible.model_dump_json())
        return session_dir

    monkeypatch.setattr(batch_module, "init_session", fake_init_session)
    monkeypatch.setattr(batch_module, "build_orchestrator", lambda *a, **k: _FakeOrchestrator())
    monkeypatch.setattr(batch_module, "SqliteSaver", _FakeSqliteSaver)

    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("Once upon a time...")

    item = batch_module.run_dataset_item(
        settings, source, "baseline_all_close", plan, length_tier=LengthTier.MEDIUM
    )

    assert captured["length_tier"] is LengthTier.MEDIUM
    assert item.status == "ok"


def test_run_batch_forwards_length_tier_to_every_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "a.txt").write_text("A story.")

    captured: list[object] = []

    def fake_run_dataset_item(  # type: ignore[no-untyped-def]
        settings, source_path, variant_name, plan, *, context="", overwrite=False,
        length_tier=LengthTier.SHORT,
    ):
        captured.append(length_tier)
        return object()

    monkeypatch.setattr(batch_module, "run_dataset_item", fake_run_dataset_item)

    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    batch_module.run_batch(
        settings,
        sources_dir,
        dimensions=["plot"],
        include_baselines=False,
        length_tier=LengthTier.MEDIUM,
    )

    assert captured
    assert all(lt is LengthTier.MEDIUM for lt in captured)
