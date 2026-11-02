"""Validity checks for the model-based primary measures, used in place of human raters.

  anchors      known-answer pairs with an expected outcome: the PSALM judge on two UNRELATED source
               texts of the corpus (lower anchor: function and expression should be low) and the
               alignment (P2) of one item's design against ANOTHER item's synthetic text (recall
               should be near zero). The paraphrase condition is the upper anchor (high by
               construction). A judge or alignment that does not separate the anchors from the
               conditions cannot support a conclusion.
  agreement    the same PSALM judgement repeated by further judges, each from another model family
               than the writers and the primary judge; Krippendorff's alpha (interval) across all
               judges on every rated aspect, and for each further judge against the primary one.
"""

from __future__ import annotations

import math


class JudgeContext:
    """The minimal context psalm_judge / align_to_design need (json calls, hints), over a bare LLM."""

    def __init__(self, llm, language: str = "en"):
        self.llm = llm
        self.language = language
        self.state: dict = {}

    def hints(self, **kw) -> dict:
        return {"language": self.language, **kw}

    async def json(self, model_role, role_text, parts, schema, **kw):
        return await self.llm.json("default", role_text, parts, schema, **kw)

    async def text(self, model_role, role_text, parts, **kw):
        return await self.llm.text("default", role_text, parts, **kw)


def krippendorff_alpha_units(units: list[list[float | None]]) -> float | None:
    """Krippendorff's alpha, interval metric, any number of coders, missing values allowed.
    Each unit lists the coders' values; units with fewer than two values are not pairable.
    alpha = 1 - D_o / D_e, with D_o = (1/n) sum_u 1/(m_u - 1) sum_{i != j} (v_i - v_j)^2 and
    D_e = 1/(n(n - 1)) sum over all ordered pairs of pairable values (Krippendorff 2011)."""
    units = [[float(v) for v in u if v is not None] for u in units]
    units = [u for u in units if len(u) >= 2]
    vals = [v for u in units for v in u]
    n = len(vals)
    if len(units) < 2:
        return None
    d_o = sum(sum((x - y) ** 2 for x in u for y in u) / (len(u) - 1) for u in units) / n
    d_e = sum((x - y) ** 2 for x in vals for y in vals) / (n * (n - 1))
    if d_e == 0:
        return 1.0 if d_o == 0 else None
    return round(1 - d_o / d_e, 4)


def krippendorff_alpha_interval(pairs: list[tuple[float, float]]) -> float | None:
    """Krippendorff's alpha (interval) for two coders."""
    return krippendorff_alpha_units([list(p) for p in pairs if p[0] is not None and p[1] is not None])


def _flat(j: dict, field: str) -> dict:
    return {(d["dimension"], s["key"]): s.get(field) for d in (j or {}).get("dimensions") or []
            for s in d.get("subdimensions") or []}


def psalm_units(judgements: list[dict], field: str) -> list[list[float | None]]:
    """One unit per (dimension, sub-dimension) rated by any judge, with each judge's value."""
    flats = [_flat(j, field) for j in judgements]
    keys = sorted(set().union(*flats)) if flats else []
    return [[f.get(k) for f in flats] for k in keys]


def checks_of(res: dict) -> dict[str, dict]:
    """The further judges' PSALM judgements of one run, by model (older results: one `psalm_check`)."""
    if res.get("psalm_checks"):
        return res["psalm_checks"]
    return {"check": res["psalm_check"]} if res.get("psalm_check") else {}


def psalm_pairs(a: dict, b: dict, field: str) -> list[tuple[float, float]]:
    """Paired ratings of one field (function_similarity / expression_similarity) between two PSALM
    judgements of the same text pair, matched by dimension and sub-dimension."""
    fa, fb = _flat(a, field), _flat(b, field)
    return [(fa[k], fb[k]) for k in fa.keys() & fb.keys() if fa[k] is not None and fb[k] is not None]


def mean_rating(j: dict, field: str) -> float | None:
    v = [s.get(field) for d in (j or {}).get("dimensions") or [] for s in d.get("subdimensions") or []
         if s.get(field) is not None]
    return round(sum(v) / len(v), 3) if v else None


def summarise(results: dict[str, dict]) -> dict:
    """Corpus-level summary of the validity checks over all judged runs."""
    uf, ue, af, ae, rec, ff = [], [], [], [], [], []
    pair_f: dict[str, list] = {}
    pair_e: dict[str, list] = {}
    for res in results.values():
        own, checks = res.get("psalm_own"), checks_of(res)
        if own and checks:
            js = [own, *checks.values()]
            uf += psalm_units(js, "function_similarity")
            ue += psalm_units(js, "expression_similarity")
            for m, chk in checks.items():
                pair_f.setdefault(m, []).extend(psalm_pairs(own, chk, "function_similarity"))
                pair_e.setdefault(m, []).extend(psalm_pairs(own, chk, "expression_similarity"))
        an = res.get("psalm_anchor")
        if an:
            af.append(mean_rating(an, "function_similarity"))
            ae.append(mean_rating(an, "expression_similarity"))
        al = res.get("alignment_anchor")
        if al and al.get("events_recall") is not None:
            rec.append(al["events_recall"])
        if own:
            ff.append(mean_rating(own, "function_similarity"))

    def m(x):
        x = [v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))]
        return round(sum(x) / len(x), 3) if x else None

    return {"judge_agreement": {"function_alpha": krippendorff_alpha_units(uf), "expression_alpha": krippendorff_alpha_units(ue),
                                "aspects": len(uf), "judges": 1 + len(pair_f),
                                "pairwise": {k: {"function_alpha": krippendorff_alpha_interval(pair_f[k]),
                                                 "expression_alpha": krippendorff_alpha_interval(pair_e[k])} for k in pair_f}},
            "psalm_lower_anchor": {"function_mean": m(af), "expression_mean": m(ae), "pairs": len(af),
                                   "conditions_function_mean": m(ff)},
            "alignment_lower_anchor": {"events_recall_mean": m(rec), "pairs": len(rec)}}


def judge_summary(j: dict) -> dict:
    """One judge's headline results, on 0-1 scales: PSALM function (fidelity on kept dimensions), PSALM
    expression (on changed dimensions), and the story and style ratings."""
    ps, co, st = j.get("psalm") or {}, j.get("content") or {}, j.get("style") or {}
    return {"model": j.get("model"), "psalm_function": ps.get("fidelity"), "psalm_expression": ps.get("appropriation"),
            "content": co.get("score"), "style": st.get("score"),
            "failed": [k for k in ("psalm", "content", "style") if str((j.get(k) or {}).get("reason_missing") or "")
                       .startswith("the judge failed")]}


def panel_agreement(judges: list[dict]) -> dict:
    """Agreement of several judges on one run: Krippendorff's alpha (interval) on the 36 PSALM function and
    expression ratings, and the spread of every headline result across judges."""
    ps = [j.get("psalm") for j in judges if (j.get("psalm") or {}).get("dimensions")]
    out: dict = {"judges": len(judges),
                 "psalm_function_alpha": krippendorff_alpha_units(psalm_units(ps, "function_similarity")) if len(ps) > 1 else None,
                 "psalm_expression_alpha": krippendorff_alpha_units(psalm_units(ps, "expression_similarity")) if len(ps) > 1 else None}
    sums = [judge_summary(j) for j in judges]
    for k in ("psalm_function", "psalm_expression", "content", "style"):
        v = [s[k] for s in sums if s[k] is not None]
        out[k] = {"mean": round(sum(v) / len(v), 3), "min": min(v), "max": max(v), "n": len(v)} if v else None
    a = out["psalm_function_alpha"]
    out["reading"] = (None if a is None else "reliable (alpha >= 0.8)" if a >= 0.8 else
                      "tentative (0.667 <= alpha < 0.8)" if a >= 0.667 else "the judges disagree (alpha < 0.667)")
    return out
