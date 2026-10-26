"""Language-variety preservation: dialect / historical spelling must survive synthesis."""

from psalm_saga.artifacts import LanguageVariety, VarietyMarker
from psalm_saga.pipeline import Pipeline
from psalm_saga.text.language import language_directive
from psalm_saga.text.variety import mismatch_note, resolve, variety_share, verify_markers
from tests.conftest import DATA, FAKE

ARCHAIC = (DATA / "nl_archaic.txt").read_text(encoding="utf-8")

PROPOSED = [
    VarietyMarker(variety_form="zoo", standard_form="zo", feature="pre-1947 spelling"),
    VarietyMarker(variety_form="mensch", standard_form="mens", feature="-sch spelling"),
    VarietyMarker(variety_form="visch", standard_form="vis", feature="-sch spelling"),
    VarietyMarker(variety_form="gij", standard_form="jij", feature="archaic pronoun"),
    VarietyMarker(variety_form="zeide", standard_form="zei", feature="archaic past tense"),
    VarietyMarker(variety_form="den", standard_form="de", feature="case ending"),
    VarietyMarker(variety_form="Hendrik", standard_form="", feature="a name, must be dropped"),  # occurs, but...
    VarietyMarker(variety_form="thans", standard_form="nu", feature="not in this text"),  # hallucinated
]


def detected() -> LanguageVariety:
    v = LanguageVariety(standard=False, name="19th-century Dutch (De Vries-Te Winkel spelling)",
                        description="-sch spellings, 'zoo', 'gij', case endings.", markers=verify_markers(ARCHAIC, PROPOSED))
    v.source_share = variety_share(ARCHAIC, v)["share"]
    return v


def test_markers_are_verified_against_the_source():
    kept = {m.variety_form for m in verify_markers(ARCHAIC, PROPOSED)}
    assert {"zoo", "mensch", "visch", "gij", "zeide"} <= kept
    assert "thans" not in kept  # never occurs in the source
    assert "Hendrik" not in kept  # a name, not a variety form
    assert "den" not in kept  # the standard 'de' is more frequent in the source, so 'den' is not characteristic


def test_share_separates_archaic_from_modern():
    v = detected()
    modern = ARCHAIC.replace("zoo", "zo").replace("mensch", "mens").replace("visch", "vis").replace(
        "zeide", "zei").replace("gij", "jij").replace("Gij", "Jij")
    assert v.source_share > 0.9
    assert variety_share(modern, v)["share"] < 0.1
    assert mismatch_note(modern, v, "Dutch") is not None
    assert mismatch_note(ARCHAIC, v, "Dutch") is None


def test_resolution_rules():
    v = detected()
    assert resolve("auto", v, "preserve") is v
    assert resolve("auto", v, "abstract") is v
    assert resolve("auto", v, "regenerate") is None  # a regenerated style is not tied to the source's variety
    assert resolve("modern", v, "preserve") is None
    custom = resolve("Brabants dialect in de dialogen", None, "preserve")
    assert custom and not custom.standard and "Brabants" in custom.name


def test_directive_stops_modernising():
    assert "conventions, idiom and punctuation of literary Dutch" in language_directive("nl")
    d = language_directive("nl", detected())
    assert "NOT in contemporary standard Dutch" in d and "literary Dutch" not in d


def _run(runs, *extra, preset="no_review", run_id=None):
    p = Pipeline.create(preset, runs_dir=runs, source=ARCHAIC, run_id=run_id, overrides=[*FAKE, *extra])
    p.store.write_json("variety.json", detected())  # what detection returns on a real model
    return p


async def test_modernised_drafts_are_caught(runs):
    p = _run(runs)
    await p.run()
    spec = p.store.read_json("spec.json")
    assert spec["variety"]["name"].startswith("19th-century Dutch")
    assert any(e["type"] == "variety_mismatch" for e in p.store.events())
    ev = p.store.read_json("evaluation.json")["variety"]
    assert ev["applicable"] and ev["source_share"] > 0.9 and ev["retention"] < 0.5
    assert ev["standard_forms_in_synthetic"]  # names the modern forms that crept in


async def test_variety_is_kept_end_to_end(runs):
    p = _run(runs, "models.default.extra.fake_follow_variety=true")
    await p.run()
    assert not any(e["type"] == "variety_mismatch" for e in p.store.events())
    ev = p.store.read_json("evaluation.json")["variety"]
    assert ev["target"] == "kept" and ev["retention"] > 0.8


async def test_modern_option_produces_a_modernised_corpus(runs):
    p = _run(runs, "language.variety=modern")
    await p.run()
    assert p.store.read_json("spec.json")["variety"] is None
    assert not any(e["type"] == "variety_mismatch" for e in p.store.events())
    ev = p.store.read_json("evaluation.json")["variety"]
    assert ev["target"].startswith("modernised") and ev["applicable"]
