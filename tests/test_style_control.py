import json

from psalm_saga.artifacts import Entity, Rename, TransformMap
from psalm_saga.pipeline import Pipeline
from psalm_saga.stages.base import RunContext
from psalm_saga.stages.transform import apply_renames, complete_renames, is_name_form
from psalm_saga.text.metrics import stylometrics
from psalm_saga.text.style import distance, rhythm_brief, shape, style_gaps
from tests.conftest import DATA, FAKE

LONG = ("In den vroegen morgen, toen de mist nog over de weiden hing en de koeien stil in het natte gras stonden, "
        "ging de oude vrouw met haar mand naar de markt, want zij had beloofd de eieren te brengen, en zij hield "
        "altijd haar woord, hoe koud het ook was. ")


def test_name_forms_and_composites():
    assert is_name_form("Vrouw Holle") and is_name_form("Adelheid") and is_name_form("Graaf van Rotsburg")
    for generic in ("de moeder", "het meisje", "het", "Vrouw", "weide", "Het grote kasteel", "Veld met hoog gras", "mama"):
        assert not is_name_form(generic), generic
    ents = [Entity(id="e1", name="Vrouw Holle", aliases=["de oude vrouw", "Holle"]),
            Entity(id="e2", name="Adelheid", aliases=["het meisje", "het zusje"])]
    tm = complete_renames(TransformMap(renames=[
        Rename(original="Vrouw Holle", new="Vrouw Ratelveer"), Rename(original="Holle", new="Ratelveer"),
        Rename(original="het huis van Vrouw Holle", new="het Berkenhuis van Vrouw Holle"),  # would leak "Holle"
        Rename(original="Adelheid", new="Lijsbeth"), Rename(original="het meisje", new="Lijsbeth"),
        Rename(original="het", new="de")]), ents)
    m = tm.as_dict()
    assert "het meisje" not in m and "het" not in m
    assert m["het huis van Vrouw Holle"] == "het huis van Vrouw Ratelveer"
    out = apply_renames("Het meisje liep naar het huis van Vrouw Holle; Adelheids moeder wachtte.", m)
    assert out == "Het meisje liep naar het huis van Vrouw Ratelveer; Lijsbeths moeder wachtte."


def test_style_distance_gaps_and_brief():
    src = (DATA / "nl_archaic.txt").read_text(encoding="utf-8")
    t = stylometrics(src, "nl")
    assert distance(t, t) == 0.0
    choppy = "Zij liep. Het was koud.\n\n„Kom mee!” riep hij.\n\nZij ging. Hij volgde.\n\n" * 30
    m = stylometrics(choppy, "nl")
    assert distance(m, t) > 0.3
    gaps = " ".join(style_gaps(m, t))
    assert "Sentences average" in gaps and "Paragraphs average" in gaps
    no_dialogue = dict(t, dialogue_paragraph_share=0.0)
    assert "reported speech" in " ".join(style_gaps(m, no_dialogue))
    brief = rhythm_brief(no_dialogue, shape(src))
    assert "Do not write dialogue" in brief and "Sentences: average" in brief and "A quarter" in brief


async def test_conform_keeps_only_improvements(runs, nl_text, monkeypatch):
    calls = {"n": 0}
    real = RunContext.text

    async def fake_text(self, model_role, role_text, parts, **kw):
        tag = kw.get("tag", "")
        if tag.startswith("conform:"):
            calls["n"] += 1
            from psalm_saga.text.chunking import split_chapters

            if calls["n"] == 1:  # first revision makes things worse: must be discarded
                return "Kort. Heel kort.\n\nNog korter.\n\n" * 40
            idx = int(tag.split(":ch")[1].split("r")[0])
            return split_chapters(self.store.read_text("input/source.txt"))[idx - 1].text  # on target by construction
        return await real(self, model_role, role_text, parts, **kw)

    monkeypatch.setattr(RunContext, "text", fake_text)
    p = Pipeline.create("full", runs_dir=runs, source=(DATA / "nl_archaic.txt").read_text(encoding="utf-8"),
                        overrides=[*FAKE, "stages.conform.params.max_length_change=5", "stages.review.enabled=false"],
                        run_id="conf")
    await p.run()
    logs = [json.loads(f.read_text(encoding="utf-8")) for f in p.store.glob("conform/ch_*.json")]
    assert logs and calls["n"] > 0
    for log in logs:
        assert log["distance_after"] <= log["distance_before"]
        prev = log["distance_before"]
        for r in log["rounds"]:
            if r["kept"]:
                assert r["distance"] < prev
                prev = r["distance"]
    rounds = [r for log in logs for r in log["rounds"]]
    assert any(r["kept"] for r in rounds) and any(not r["kept"] for r in rounds)
    assert min(log["distance_after"] for log in logs) < 0.05
    ev = p.store.read_json("evaluation.json")
    assert "fidelity" in ev
    prof = p.store.read_json("profile.json")
    assert prof["shape"]["sentence_quantiles"]


async def test_conform_skips_when_policy_regenerates_style(runs, nl_text):
    p = Pipeline.create("full", runs_dir=runs, source=nl_text,
                        overrides=[*FAKE, "transform.policy.writing_style=regenerate"], run_id="noconf")
    await p.run()
    assert not list(p.store.glob("conform/ch_*.json"))


async def test_old_run_can_adopt_new_stages(runs, nl_text):
    from psalm_saga.config import load_config

    cfg = load_config("full", FAKE)
    del cfg.stages["conform"]
    p = Pipeline.create(cfg, runs_dir=runs, source=nl_text, run_id="old")
    await p.run()
    p = Pipeline.open(p.store.root)
    assert p.missing_stages() == ["conform"]
    assert p.adopt_missing_stages() == ["conform"]
    assert not p.missing_stages() and "conform" in Pipeline.open(p.store.root).config.stages
    await p.run()
    assert list(p.store.glob("conform/ch_*.json"))


async def test_drafting_prompt_carries_rhythm_and_form(runs, monkeypatch):
    """Guards against the targets silently not reaching the writer (they once did not)."""
    import psalm_saga.llm.fake as fk

    seen: list[str] = []
    orig = fk.FakeBackend.complete

    async def spy(self, *, messages, schema, hints, extra=None):
        if schema is None and "target_words" in hints:
            seen.append(json.dumps(messages, ensure_ascii=False))
        return await orig(self, messages=messages, schema=schema, hints=hints, extra=extra)

    monkeypatch.setattr(fk.FakeBackend, "complete", spy)
    prose = Pipeline.create("full", runs_dir=runs, source=(DATA / "nl_archaic.txt").read_text(encoding="utf-8"),
                            overrides=[*FAKE, "stages.review.enabled=false"], run_id="rp")
    await prose.run(until="draft")
    assert seen and all("Rhythm scaffold" in s and "These are measurements of the source" in s for s in seen)
    seen.clear()
    verse = Pipeline.create("full", runs_dir=runs, source=(DATA / "nl_verse.txt").read_text(encoding="utf-8"),
                            overrides=[*FAKE, "stages.review.enabled=false"], run_id="rv")
    await verse.run(until="draft")
    assert seen and all("the source is VERSE" in s and "Rhythm scaffold" not in s for s in seen)
    seen.clear()
    off = Pipeline.create("no_conform", runs_dir=runs, source=(DATA / "nl_archaic.txt").read_text(encoding="utf-8"),
                          overrides=[*FAKE], run_id="roff")
    await off.run(until="draft")
    assert seen and not any("Rhythm scaffold" in s for s in seen)
