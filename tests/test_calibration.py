import random

from psalm_saga.eval.automatic import kg_scores
from psalm_saga.eval.features import ks_pvalue, ks_statistic
from psalm_saga.eval.grading import grades
from psalm_saga.pipeline import Pipeline
from tests.conftest import FAKE


def test_ks_pvalue_tracks_sample_size():
    rng = random.Random(0)
    a = [rng.gauss(20, 8) for _ in range(60)]
    b = [rng.gauss(20, 8) for _ in range(60)]
    d = ks_statistic(a, b)
    assert ks_pvalue(d, 60, 60) > 0.05  # same distribution: no detectable difference
    c = [rng.gauss(35, 8) for _ in range(60)]
    assert ks_pvalue(ks_statistic(a, c), 60, 60) < 0.001
    assert ks_pvalue(0.2, 20, 20) > ks_pvalue(0.2, 2000, 2000)  # the same gap is weaker evidence in small samples


def test_distribution_grade_uses_the_test():
    rep = {"distributions": {"sentence_length": {"ks": 0.25, "ks_p": 0.2}, "paragraph_length": {"ks": 0.25, "ks_p": 0.001},
                             "word_length": {"ks": 0.05, "ks_p": 0.0}}}
    g = grades(rep)
    assert g["sentence_overlap"]["grade"] == "good" and g["paragraph_overlap"]["grade"] == "bad"
    assert g["word_overlap"]["grade"] == "good"  # negligible gap, however significant


def test_kg_relative_to_extractor_agreement():
    summary = {"nodes": {"event": {"kept": 6, "changed": 0, "source_only": 4, "recall": 0.6}}, "edges": {}}
    ceiling = {"nodes": {"event": {"recall": 0.75}}, "edges": {}}
    s = kg_scores(summary, ceiling)["events"]
    assert s["recall"] == 0.6 and s["ceiling"] == 0.75 and s["relative"] == 0.8 and s["value"] == 0.8
    assert kg_scores(summary, None)["events"]["value"] == 0.6


async def test_recover_calibrates_and_essays_skip_narrative_measures(runs, nl_text):
    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="cal")
    await p.run()
    assert p.store.exists("calibration/bible_source.json") and p.store.exists("text_kind.json")
    ev = p.store.read_json("evaluation.json")
    assert "structure_ceiling" in ev and all("value" in v for v in ev["kg"].values())
    # Pretend the source is an essay: narrative measures become not applicable, not red.
    p.store.write_json("text_kind.json", {"kind": "essay", "narrator": "first", "has_cast": False, "note": ""})
    await p.run(rerun_from="evaluate")
    ev = p.store.read_json("evaluation.json")
    assert "kg_events" not in ev["grades"] and ev["not_measurable"]["kg_events"].startswith("not applicable: the source is an essay")


def test_style_grade_relative_to_source_self_agreement():
    from psalm_saga.eval.grading import grades
    rep = {"fidelity": {"stylometric_mean_rel_diff": 0.25, "function_word_cosine": 0.88},
           "self_agreement": {"style_drift": 0.21, "function_word_cosine": 0.90}}
    g = grades(rep)
    assert g["style_drift"]["grade"] == "good" and "source vs itself" in g["style_drift"]["rule"]
    assert g["fw_cosine"]["grade"] == "good"
    rep["self_agreement"] = {}
    g = grades(rep)
    assert g["style_drift"]["grade"] == "bad"
