import pytest

from psalm_saga.artifacts import Entity, Rename, TransformMap
from psalm_saga.config import load_config, preset_names
from psalm_saga.llm.jsonutil import extract_json
from psalm_saga.stages.draft import clean_prose
from psalm_saga.stages.transform import apply_renames, complete_renames
from psalm_saga.taxonomy import load_taxonomy
from psalm_saga.text.chunking import chunk_chapters, split_chapters
from psalm_saga.text.language import detect_language, label
from psalm_saga.text.metrics import leakage_report, stylometrics, verbatim_spans

# ------------------------------------------------------------------ config


def test_all_presets_load():
    names = preset_names()
    assert {"full", "no_review", "no_spec", "flat", "flat_spec", "paraphrase", "agents_room", "fast"} <= set(names)
    for n in names:
        cfg = load_config(n)
        assert cfg.models["default"].name


def test_inheritance_and_overrides():
    cfg = load_config("no_review", ["models.default.name=openai/gpt-5.5", "stages.guard.params.min_span=8"])
    assert not cfg.stage("review").enabled
    assert cfg.stage("draft").impl == "chapter"  # inherited from full
    assert cfg.models["default"].name == "openai/gpt-5.5"
    assert cfg.stage("guard").params["min_span"] == 8


def test_partial_policy_override_keeps_other_dimensions():
    cfg = load_config("full", {"transform.policy.character": "regenerate"})
    assert cfg.transform.policy["character"] == "regenerate"
    assert cfg.transform.policy["world_building"] == "abstract"
    assert cfg.transform.policy["writing_style"] == "preserve"


def test_role_models_inherit_default_fields():
    cfg = load_config("fast")
    assert cfg.models["extract"].name.endswith("haiku-5-5")
    assert cfg.models["extract"].max_output_tokens == cfg.models["default"].max_output_tokens
    assert cfg.model_for("draft").name == cfg.models["default"].name


def test_unknown_preset():
    with pytest.raises(ValueError, match="Unknown preset"):
        load_config("nope")


def test_taxonomy_shape():
    tax = load_taxonomy("psalm")
    assert len(tax.dimensions) == 6
    assert all(len(d.subdimensions) == 6 for d in tax.dimensions)


# ------------------------------------------------------------------ text


def test_split_chapters_skips_table_of_contents():
    toc = "INHOUD\n\nHoofdstuk 1\n\nHoofdstuk 2\n\n"
    body = "\n\n".join(f"Hoofdstuk {i}\n\n" + "woord " * 300 for i in (1, 2))
    chs = split_chapters(toc + body)
    assert [c.title for c in chs] == ["Hoofdstuk 1", "Hoofdstuk 2"]
    assert all(c.words >= 300 for c in chs)


def test_split_chapters_roman_and_markdown():
    text = "\n\n".join(f"{h}\n\n" + "word " * 200 for h in ("I.", "II. The Storm", "## III", "Kapitel 4"))
    assert len(split_chapters(text)) == 4


def test_headingless_text_becomes_pseudo_chapters():
    text = "\n\n".join("word " * 400 for _ in range(40))  # 16k words, no headings
    chs = split_chapters(text, pseudo_chapter_words=5000)
    assert len(chs) >= 3
    assert all(c.words <= 5400 for c in chs)


def test_long_chapter_is_chunked():
    text = "Chapter 1\n\n" + "\n\n".join("word " * 500 for _ in range(30)) + "\n\nChapter 2\n\n" + "word " * 300
    chunks = chunk_chapters(split_chapters(text), chunk_words=4000)
    assert max(c.words for c in chunks) <= 4500
    assert {c.chapter for c in chunks} == {1, 2}


@pytest.mark.parametrize(("text", "code"), [
    ("De man liep door de straat en hij zag dat het huis van zijn vader er niet meer was. " * 10, "nl"),
    ("The man walked down the street and he saw that his father's house was no longer there. " * 10, "en"),
    ("Der Mann ging die Straße entlang und sah, dass das Haus seines Vaters nicht mehr da war. " * 10, "de"),
])
def test_language_detection(text, code):
    assert detect_language(text, use_lingua=False).code == code


def test_localised_labels():
    assert label("nl", "chapter") == "Hoofdstuk"
    assert label("de", "chapter") == "Kapitel"
    assert label("xx", "chapter") == "Chapter"


def test_stylometrics_and_leakage():
    src = "the quick brown fox jumps over the lazy dog while the farmer sleeps soundly in the old red barn tonight"
    tgt = "Yesterday the quick brown fox jumps over the lazy dog while the farmer sleeps soundly in a house."
    spans = verbatim_spans(src, tgt, min_len=12)
    assert spans and spans[0]["length"] == 15
    rep = leakage_report(src, tgt, ["Farmer", "Barn"])
    assert rep["longest_copied_span_words"] == 15
    m = stylometrics('He came. "Where?" she asked.\n\nThey left, slowly; quietly.', "en")
    assert m["dialogue_paragraph_share"] == 0.0 and m["sentences"] == 3


def test_clean_prose_strips_model_headings():
    raw = "## Chapter 3: The Storm\n\n**The Storm**\n\nHet regende.\n\n# stray heading\n\nNog meer regen."
    assert clean_prose(raw) == "Het regende.\n\nNog meer regen."
    assert clean_prose("Hoofdstuk 2\n\nTekst.") == "Tekst."


def test_renames_cover_aliases_and_possessives():
    ents = [Entity(id="e1", name="Deborah Jenkyns", aliases=["Miss Jenkyns", "Deborah"]),
            Entity(id="e2", name="Cranford", kind="place")]
    tmap = complete_renames(TransformMap(renames=[Rename(original="Deborah Jenkyns", new="Hendrika Vos"),
                                                  Rename(original="Cranford", new="Wolderveen")]), ents)
    m = tmap.as_dict()
    assert m["Miss Jenkyns"] == "Miss Vos" and m["Deborah"] == "Hendrika" and m["Jenkyns"] == "Vos"
    out = apply_renames("Deborah's sister lived in Cranford. Miss Jenkyns agreed.", m)
    assert out == "Hendrika's sister lived in Wolderveen. Miss Vos agreed."


def test_extract_json_tolerates_wrapping():
    assert extract_json('Sure! ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    with pytest.raises(ValueError):
        extract_json("no json here")
