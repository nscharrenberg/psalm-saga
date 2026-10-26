import json
import shutil
from pathlib import Path

from psalm_saga.artifacts import Bible, Entity
from psalm_saga.eval.corpus import (
    ItemRecord,
    classifier_transfer,
    corpus_report,
    cosine_delta,
    dispersion_ratio,
    distinguishability,
    rank_agreement,
    replicate_analyses,
)
from psalm_saga.eval.features import bible_characters, char_ngram_jsd, gender_shares, proper_noun_tokens
from psalm_saga.experiments.runner import run_experiment
from tests.conftest import DATA


def _recs(n=12, shrink=1.0, noise=0.0):
    import random

    rng = random.Random(1)
    out = []
    for i in range(n):
        x = 10 + i
        y = 10 + (x - 15.5) * shrink + 5.5 + rng.gauss(0, noise)
        period = "early" if i < n // 2 else "late"
        out.append(ItemRecord(item=f"b{i}", features={"sent": {"source": x, "synthetic": y},
                                                       "dial": {"source": i % 3, "synthetic": i % 3}},
                              metadata={"period": period, "year": str(1850 + 5 * i)}))
    return out


def test_rank_dispersion_and_replication():
    exact = _recs()
    r1 = rank_agreement(exact)
    assert r1["sent"]["spearman"] == 1.0 and r1["sent"]["ci95"]
    assert dispersion_ratio(exact)["sent"]["ratio"] == 1.0
    flat = dispersion_ratio(_recs(shrink=0.2))["sent"]
    assert flat["ratio"] < 0.3  # homogenisation is detected
    rep = replicate_analyses(exact, [{"feature": "sent", "by": "period", "groups": ["early", "late"]},
                                     {"feature": "sent", "vs": "year"}])
    assert rep[0]["replicates"] and rep[0]["source"]["estimate"] == rep[0]["synthetic"]["estimate"] > 0
    assert rep[1]["source"]["estimate"] == 1.0 and rep[1]["replicates"]
    reversed_ = [ItemRecord(item=r.item, features={"sent": {"source": r.features["sent"]["source"],
                                                            "synthetic": -r.features["sent"]["source"]}},
                            metadata=r.metadata) for r in exact]
    assert replicate_analyses(reversed_, [{"feature": "sent", "vs": "year"}])[0]["replicates"] is False


def test_distinguishability():
    same = distinguishability(_recs())
    assert same["cv_accuracy"] <= 0.6
    shifted = [ItemRecord(item=r.item, features={"sent": {"source": r.features["sent"]["source"],
                                                          "synthetic": r.features["sent"]["source"] + 30}})
               for r in _recs()]
    d = distinguishability(shifted)
    assert d["cv_accuracy"] >= 0.9 and d["pmse_ratio"] > same["pmse_ratio"]


def test_classifier_transfer_and_cosine_delta():
    recs = []
    for i in range(6):
        lab = "a" if i % 2 else "b"
        base = 5.0 if lab == "a" else 15.0
        ch = [{"f1": base + k * 0.1, "f2": 1.0 + k * 0.01} for k in range(4)]
        recs.append(ItemRecord(item=f"b{i}", features={}, source_chapters=ch, synthetic_chapters=ch, metadata={"genre": lab}))
    t = classifier_transfer(recs, "genre")
    assert t["tstr_accuracy"] == t["trtr_accuracy"] == 1.0 and t["tstr_over_trtr"] == 1.0
    texts = [(DATA / f).read_text(encoding="utf-8") for f in ("nl_storm.txt", "nl_brieven.txt", "nl_archaic.txt", "en_harbour.txt")]
    recs = [ItemRecord(item=str(i), features={}, source_text=t, synthetic_text=t) for i, t in enumerate(texts)]
    cd = cosine_delta(recs)
    assert cd["top1_accuracy"] == 1.0 and cd["mean_delta_own"] < 1e-6 and cd["chance"] == 0.25
    rep = corpus_report(_recs(), [{"feature": "sent", "vs": "year"}], "period")
    assert {"R1_rank_agreement", "R2_dispersion", "R3_replication", "R4_distinguishability", "R5_classifier_transfer"} <= set(rep)


def test_distribution_comparison():
    from psalm_saga.eval.features import compare_distribution, ks_statistic

    same = compare_distribution([1, 2, 3, 4, 10], [1, 2, 3, 4, 10], [0, 2, 4, 1e9], "w")
    assert same["overlap"] == 1.0 and same["ks"] == 0.0
    apart = compare_distribution([1, 1, 1], [9, 9, 9], [0, 2, 4, 1e9], "w")
    assert apart["overlap"] == 0.0 and apart["ks"] == 1.0
    assert ks_statistic([1, 2, 3, 4], [3, 4, 5, 6]) == 0.5


def test_text_features():
    a = "Anna zag de zee. Zij liep naar huis en zij lachte. Hij bleef staan. Anna riep hem."
    b = "Mira zag de zee. Zij liep naar huis en zij lachte. Hij bleef staan. Mira riep hem."
    assert char_ngram_jsd(a, b, {"Anna", "Mira"}) == 0.0
    assert char_ngram_jsd(a, "Totally different English words here, nothing alike.", set()) > 0.3
    bible = Bible(entities=[Entity(id="e1", name="Anna", gender="female"), Entity(id="e2", name="Piet", gender="male")])
    assert gender_shares(a, "nl", bible_characters(bible))["female_mention_share"] is None  # too few to be stable
    g = gender_shares(" ".join([a] * 10), "nl", bible_characters(bible))
    assert g["female_mention_share"] == 1.0 and g["female_pronoun_share"] == round(2 / 4, 4)
    syn = bible_characters(bible, {"Anna": "Mira", "Piet": "Joost"})
    assert gender_shares(" ".join([b] * 10), "nl", syn)["female_mention_share"] == 1.0
    assert "anna" in proper_noun_tokens(a) and "zij" not in proper_noun_tokens(a)


async def test_experiment_with_corpus_instruments(tmp_path):
    shutil.copytree(DATA, tmp_path / "data")
    (tmp_path / "meta.csv").write_text(
        "item,title,period,year\nnl_storm,De storm,early,1890\nnl_brieven,Brieven,late,1925\n"
        "nl_archaic,Oud,early,1870\nen_ledger,The Ledger,late,1930\n", encoding="utf-8")
    plan = tmp_path / "plan.yaml"
    inputs = ", ".join(f'{{path: "data/{f}.txt", kind: source}}' for f in ("nl_storm", "nl_brieven", "nl_archaic", "en_ledger"))
    plan.write_text(f"""
name: inst
output: {tmp_path / 'out'}
inputs: [{inputs}]
conditions: {{full: {{preset: full}}}}
models: {{fake: {{models.default.name: fake/x}}}}
metadata: meta.csv
analyses: [{{feature: mean_sentence_words, by: period, groups: [early, late]}}, {{feature: dialogue_paragraph_share, vs: year}}]
tstr_label: period
judge: {{model: fake/judge, instruments: [emotional_arc, surface_reuse, reconstruction]}}
""")
    await run_experiment(plan)
    out = tmp_path / "out"
    ev = json.loads((out / "runs" / "nl_storm--full--fake--r1" / "evaluation.json").read_text(encoding="utf-8"))
    assert ev["fidelity"]["function_word_cosine"] is not None and "gender" in ev["fidelity"]
    assert ev["divergence"]["char3_jsd"] is not None and "mean_sentence_words" in ev["features"]
    d = ev["distributions"]
    assert 0 <= d["sentence_length"]["overlap"] <= 1 and abs(sum(d["sentence_length"]["source"]) - 1) < 0.01
    assert d["chapter_profile"]["length_share"]["source"] and 10 <= len(d["function_words"]) <= 30
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    corpus = summary["corpus"]["full / fake"]
    assert corpus["items"] == 4 and corpus["R1_rank_agreement"] and corpus["F1b_cosine_delta"]["items"] == 4
    assert len(corpus["R3_replication"]) == 2 and corpus["R5_classifier_transfer"]["label"] == "period"
    jd = json.loads((out / "judgements.json").read_text(encoding="utf-8"))["nl_storm--full--fake--r1"]
    assert {"emotional_arc", "surface_reuse", "reconstruction"} <= set(jd)
    assert "identified" in jd["reconstruction"]
    report = Path(out / "report.md").read_text(encoding="utf-8")
    assert "## Corpus-level validity" in report and "R3 analysis replication" in report and "R5 classifier transfer" in report
    page = (out / "report.html").read_text(encoding="utf-8")
    assert "<svg" in page and "mean sentence words" in page and len(corpus["values"]["mean_sentence_words"]["source"]) == 4
