"""Measures that cannot be taken on a text are reported as such, not as a failing value."""

from psalm_saga.eval.automatic import kg_scores, varies_beyond_chance
from psalm_saga.stages.plan import _budget
from psalm_saga.text.form import verse_budget


def test_kg_not_measurable_when_source_does_not_agree_with_itself():
    summary = {"edges": {"relation:social": {"kept": 0, "changed": 0, "source_only": 4, "recall": 0.0}}}
    ceiling = {"edges": {"relation:social": {"kept": 0, "changed": 0, "source_only": 4, "recall": 0.0}}}
    row = kg_scores(summary, ceiling)["social"]
    assert row["value"] is None and row["ceiling"] == 0.0
    assert kg_scores(summary, None)["social"]["value"] == 0.0  # no calibration: raw recall stands


def test_permutation_test_separates_signal_from_noise():
    flat = [[10.0, 30.0, 20.0, 15.0, 25.0] for _ in range(6)]
    assert not varies_beyond_chance(flat)
    moving = [[5.0, 6.0, 7.0, 5.0, 6.0], [40.0, 42.0, 38.0, 41.0, 39.0], [6.0, 5.0, 7.0, 6.0, 5.0],
              [39.0, 40.0, 41.0, 42.0, 38.0], [5.0, 7.0, 6.0, 5.0, 6.0]]
    assert varies_beyond_chance(moving)


def test_budget_floor_does_not_inflate_short_texts():
    assert sum(_budget(300, [1.0, 1.0, 1.0])) == 300
    assert _budget(30000, [1.0, 0.001]) [1] == 150


def test_verse_budget_in_lines_and_stanzas():
    out = verse_budget({"line_words_mean": 5.0, "lines_per_stanza_mode": 4}, 100)
    assert "5 stanzas of 4 lines" in out


def test_presence_merges_sparse_segments_and_jaccard_needs_pairs():
    from psalm_saga.artifacts import Bible
    from psalm_saga.eval.automatic import character_fidelity

    names = ["Anna", "Bert", "Cees"]
    bible = Bible.model_validate({"entities": [{"id": n, "name": n, "kind": "character", "chapters": [1], "mentions": 9}
                                               for n in names], "relations": [], "chapters": []})
    units = [f"{names[i % 3]} walked." for i in range(10)]  # one mention per unit: far too sparse
    out = character_fidelity(units, units, bible, {})
    assert out["units"] == 3 and out["chapter_presence_pearson"] is None
    assert out["cooccurrence_jaccard"] is not None or out["source_pairs"] < 3


def test_several_fixes_combine_from_the_earliest_stage():
    from psalm_saga.fixes import combine_fixes

    style = {"id": "style", "rerun_from": "draft", "overrides": {"stages.draft.params.extra_instruction": "Match the rhythm."}}
    variety = {"id": "variety", "rerun_from": "draft", "overrides": {"stages.draft.params.extra_instruction": "Use 't."}}
    plan = {"id": "structure", "rerun_from": "plan", "overrides": {"stages.plan.params.extra_instruction": "Keep scenes."}}
    frm, ov = combine_fixes([style, variety, plan])
    assert frm == "plan"
    assert ov["stages.draft.params.extra_instruction"] == "Match the rhythm.\n\nUse 't."
    assert ov["stages.plan.params.extra_instruction"] == "Keep scenes."


def test_scores_are_normalised_with_formulas():
    from psalm_saga.eval.grading import BY_KEY, grades

    rep = {"distributions": {"sentence_length": {"ks": 0.1, "ks_p": 0.01}}, "length": {"ratio": 1.2},
           "fidelity": {"characters": {"salience_spearman": -0.4}}, "leakage": {"names_leaked": 1}}
    g = grades(rep)
    assert g["sentence_overlap"]["score"] == 0.8 and g["sentence_overlap"]["grade"] == "good"   # 1 − 0.1/0.5
    assert g["length_ratio"]["score"] == 0.6 and g["length_ratio"]["grade"] == "warn"           # 1 − 0.2/0.5
    assert g["salience"]["score"] == 0.0 and g["salience"]["grade"] == "bad"                    # max(0, r)
    assert g["names"]["grade"] == "bad"                                                          # any leaked name
    assert all(0 <= v["score"] <= 1 for v in g.values() if v["score"] is not None)
    assert "inverted" in BY_KEY["sentence_overlap"].formula
