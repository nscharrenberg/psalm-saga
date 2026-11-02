"""Pre-registered hypothesis tests over an experiment's results (results.csv rows).

Every test compares conditions *per item*: the samples of an item are averaged first, so the item
(the book) stays the unit of analysis, and the paired differences between two conditions are
resampled over items (bootstrap, `B` resamples; Koehn 2004; Dror et al. 2018). Within a family of
tests the one-sided p-values are adjusted with Holm's procedure. Tests run separately per writer
model unless `per_model: false`.

A test in the plan (`hypotheses:`):

    - id: H1a
      family: H1                      # Holm adjustment within family (and model)
      measure: kg_events              # a graded measure key, or any results column
      better: higher                  # higher | lower | one  (one: closer to 1 is better);
                                      #   default from the measure's grading, else higher
      a: full@preserve                # the condition the claim is about
      b: no_feedback@preserve         # the comparison; omit for a one-sample test against `value`
      test: superiority               # superiority | non_inferiority | equivalence | above | below
      margin: 0.05                    # non_inferiority / equivalence: in the measure's own unit
      value: 3.5                      # above / below: the threshold (one-sample, on a's item means)

`share_below` tests a share of samples rather than a mean: `{test: share_below, measure: span,
a: full@preserve, value: 12, share: 0.95}` is supported when at least 95% of a's samples have a
value below 12 (no inference; a guardrail).

Decisions use alpha (default 0.05) on the Holm-adjusted one-sided p-value. Reported per test: the
mean difference (oriented so that positive means `a` is better), its 95% interval, the one-sided
90% bound used by the decision, the raw and adjusted p, and whether the hypothesis is supported.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict

import numpy as np

SEED = 20261027


def _direction(measure: str, better: str | None) -> str:
    if better:
        return better
    from psalm_saga.eval.grading import METRICS

    m = next((m for m in METRICS if m.key == measure), None)
    if m is None:
        return "higher"
    return {"unit": "higher", "corr": "higher", "diff": "lower", "ratio": "one"}.get(m.norm or "", "higher")


def _value(row: dict, measure: str):
    for k in (f"value.{measure}", measure):
        v = row.get(k)
        if v is None or v == "":
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(v):
            return v
    return None


def _oriented(v: float, direction: str) -> float:
    """Higher is better after orientation."""
    return -v if direction == "lower" else -abs(v - 1.0) if direction == "one" else v


def item_means(rows: list[dict], measure: str, condition: str, model: str | None) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("condition") != condition or (model is not None and r.get("model") != model):
            continue
        if r.get("status") not in (None, "done"):
            continue
        v = _value(r, measure)
        if v is not None:
            acc[r["item"]].append(v)
    return {k: statistics.fmean(v) for k, v in acc.items()}


def _boot(values: np.ndarray, B: int, rng) -> np.ndarray:
    n = len(values)
    idx = rng.integers(0, n, size=(B, n))
    return values[idx].mean(axis=1)


def _p_greater(boot: np.ndarray, threshold: float) -> float:
    """One-sided bootstrap p for H1: mean > threshold (share of resampled means at or below it)."""
    return float((1 + np.sum(boot <= threshold)) / (len(boot) + 1))


def run_test(rows: list[dict], h: dict, model: str | None, B: int = 10000) -> dict:
    measure, test = h["measure"], h.get("test", "superiority")
    direction = _direction(measure, h.get("better"))
    out = {"id": h.get("id"), "family": h.get("family", h.get("id")), "measure": measure, "test": test,
           "a": h["a"], "b": h.get("b"), "model": model, "better": direction, "margin": h.get("margin"),
           "value": h.get("value"), "label": h.get("label", "")}
    rng = np.random.default_rng(SEED)
    if test == "share_below":
        vals = [v for r in rows if r.get("condition") == h["a"] and (model is None or r.get("model") == model)
                and (v := _value(r, measure)) is not None]
        if not vals:
            return {**out, "n": 0, "status": "not applicable: no values"}
        share = sum(v < float(h["value"]) for v in vals) / len(vals)
        need = float(h.get("share", 0.95))
        return {**out, "n": len(vals), "share": round(share, 4), "required": need, "supported": share >= need,
                "status": "ok", "p": None}
    a = item_means(rows, measure, h["a"], model)
    if test in ("above", "below"):
        xs = np.array([a[k] for k in sorted(a)])
        if len(xs) < 3:
            return {**out, "n": len(xs), "status": "not applicable: fewer than 3 items"}
        boot = _boot(xs, B, rng)
        thr = float(h["value"])
        p = _p_greater(boot, thr) if test == "above" else _p_greater(-boot, -thr)
        return {**out, "n": len(xs), "mean_a": round(float(xs.mean()), 4),
                "ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
                "p": p, "status": "ok"}
    b = item_means(rows, measure, h["b"], model)
    keys = sorted(a.keys() & b.keys())
    if len(keys) < 3:
        return {**out, "n": len(keys), "status": "not applicable: fewer than 3 items with both conditions"}
    d = np.array([_oriented(a[k], direction) - _oriented(b[k], direction) for k in keys])
    boot = _boot(d, B, rng)
    margin = float(h.get("margin") or 0.0)
    res = {**out, "n": len(keys), "mean_a": round(statistics.fmean(a[k] for k in keys), 4),
           "mean_b": round(statistics.fmean(b[k] for k in keys), 4), "difference": round(float(d.mean()), 4),
           "ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
           "ci90": [round(float(np.percentile(boot, 5)), 4), round(float(np.percentile(boot, 95)), 4)],
           "status": "ok"}
    if test == "superiority":
        res["p"] = _p_greater(boot, 0.0)
    elif test == "non_inferiority":
        res["p"] = _p_greater(boot, -margin)
    elif test == "equivalence":  # two one-sided tests
        res["p"] = max(_p_greater(boot, -margin), _p_greater(-boot, -margin))
    else:
        res["status"] = f"unknown test {test!r}"
    return res


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, prev = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        v = min(1.0, (len(ps) - rank) * ps[i])
        prev = max(prev, v)
        adj[i] = prev
    return adj


def evaluate(rows: list[dict], hypotheses: list[dict], *, alpha: float = 0.05, B: int = 10000) -> dict:
    """All tests, Holm-adjusted per (family, model), with a verdict per family."""
    models = sorted({r.get("model") for r in rows if r.get("model")})
    results = []
    for h in hypotheses:
        for m in (models if h.get("per_model", True) and models else [None]):
            results.append(run_test(rows, h, m, B))
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("p") is not None:
            groups[(r["family"], r["model"])].append(r)
    for rs in groups.values():
        for r, p in zip(rs, holm([r["p"] for r in rs]), strict=True):
            r["p_holm"] = round(p, 5)
            r["p"] = round(r["p"], 5)
            r["supported"] = p < alpha
    families: dict[str, dict] = {}
    for r in results:
        f = families.setdefault(f"{r['family']} / {r['model'] or 'all'}", {"tests": 0, "supported": 0, "not_applicable": 0})
        f["tests"] += 1
        if r.get("status") != "ok":
            f["not_applicable"] += 1
        elif r.get("supported"):
            f["supported"] += 1
    for f in families.values():
        f["all_supported"] = f["tests"] > f["not_applicable"] and f["supported"] == f["tests"] - f["not_applicable"]
    return {"alpha": alpha, "bootstrap": B, "tests": results, "families": families}


def report_lines(res: dict) -> list[str]:
    if not res or not res.get("tests"):
        return []
    lines = ["", "## Hypotheses (pre-registered)", "",
             f"Paired bootstrap over items ({res['bootstrap']} resamples); one-sided p, Holm-adjusted per family and "
             f"model; α = {res['alpha']}. Difference oriented so that positive = the first condition is better.", "",
             "| test | model | measure | comparison | n | difference [95% CI] | p (Holm) | supported |",
             "|---|---|---|---|---|---|---|---|"]

    def ci(c):
        return f" [{c[0]:.3f}, {c[1]:.3f}]" if c else ""

    for r in res["tests"]:
        comp = {"superiority": f"{r['a']} > {r['b']}", "non_inferiority": f"{r['a']} ≥ {r['b']} − {r['margin']}",
                "equivalence": f"{r['a']} ≈ {r['b']} ± {r['margin']}", "above": f"{r['a']} > {r['value']}",
                "below": f"{r['a']} < {r['value']}",
                "share_below": f"≥ {r.get('required')} of {r['a']} below {r['value']}"}.get(r["test"], r["test"])
        if r.get("status") != "ok":
            lines.append(f"| {r['id']} | {r['model']} | {r['measure']} | {comp} | {r.get('n', 0)} | {r['status']} | | |")
            continue
        diff = (f"{r['share']:.3f}" if r["test"] == "share_below" else
                f"{r.get('difference', r.get('mean_a')):.3f}{ci(r.get('ci95'))}")
        p = "–" if r.get("p_holm") is None else f"{r['p_holm']:.4f}"
        lines.append(f"| {r['id']} | {r['model']} | {r['measure']} | {comp} | {r['n']} | {diff} | {p} | "
                     f"{'yes' if r.get('supported') else 'no'} |")
    lines += ["", "| family / model | tests | supported | not applicable | all supported |", "|---|---|---|---|---|"]
    for k, f in res["families"].items():
        lines.append(f"| {k} | {f['tests']} | {f['supported']} | {f['not_applicable']} | {'yes' if f['all_supported'] else 'no'} |")
    return lines


# ------------------------------------------------------------------ the paper's tests, for any plan

STORY = ("character", "plot_structure", "scene_sequence", "world_building")
RETENTION = ("sentence_overlap", "paragraph_overlap", "kg_events", "kg_causes")
MARGINS = {"sentence_overlap": 0.05, "paragraph_overlap": 0.05, "kg_events": 0.05, "kg_causes": 0.05, "salience": 0.1,
           "psalm.function.story": 0.5, "psalm.expression.story": 0.5, "psalm.function.style": 0.5, "fw_cosine": 0.02,
           "span": 2}


def _kind(setting: dict[str, str]) -> str | None:
    """preserve / reinvent / replace, from what a policy setting does to the story dimensions."""
    from psalm_saga.experiments.runner import policy_setting

    vals = {policy_setting(setting)[d] for d in STORY}
    return {"preserve": "preserve", "abstract": "reinvent", "regenerate": "replace"}.get(vals.pop()) if len(vals) == 1 else None


def default_hypotheses(conditions: dict[str, str], policies: dict[str, dict[str, str]],
                       margins: dict[str, float] | None = None) -> list[dict]:
    """The paper's five families for a plan, by preset: `full` is the procedure; `no_feedback` (H1, the
    review loop), `no_graph` (H2, the knowledge graph), the policy contrasts of the full procedure (H3),
    `paraphrase` (H4) and `flat` (H5, the single call). `conditions` maps condition name -> preset.
    Families whose conditions are missing are left out."""
    mg = {**MARGINS, **(margins or {})}
    by = {}
    for name, preset in conditions.items():
        by.setdefault(preset, name)
    full = by.get("full")
    if not full:
        return []
    pols = list(policies) or [None]
    kinds = {p: _kind(policies[p]) for p in policies}
    at = lambda c, p: f"{c}@{p}" if p else c  # noqa: E731
    H: list[dict] = []

    def t(id_, fam, measure, a, b=None, test="superiority", **kw):
        H.append({"id": id_, "family": fam, "measure": measure, "a": a, **({"b": b} if b else {}), "test": test, **kw})

    def salience_ok(p):
        return p is None or kinds.get(p) != "replace"

    if "no_feedback" in by:
        for p in pols:
            for m in (*RETENTION, *(("salience",) if salience_ok(p) else ())):
                t(f"H1.{p or 'all'}.{m}", "H1", m, at(full, p), at(by["no_feedback"], p))
            t(f"H1.{p or 'all'}.fw_cosine", "H1", "fw_cosine", at(full, p), at(by["no_feedback"], p), "non_inferiority",
              margin=mg["fw_cosine"])
    if "no_graph" in by:
        for p in pols:
            for m in ("kg_events", "kg_causes", "kg_characters", "kg_social", *(("salience",) if salience_ok(p) else ())):
                t(f"H2.{p or 'all'}.{m}", "H2", m, at(full, p), at(by["no_graph"], p))
    inv = {k: p for p, k in kinds.items() if k}
    if {"preserve", "reinvent"} <= set(inv):
        pr, re_ = inv["preserve"], inv["reinvent"]
        t("H3a", "H3", "psalm.function.story", at(full, re_), at(full, pr), "non_inferiority",
          margin=mg["psalm.function.story"], better="higher", label="re-invent keeps the function of the story dimensions")
        t("H3b", "H3", "psalm.expression.story", at(full, re_), at(full, pr), better="lower",
          label="re-invent lowers their expression")
        if "replace" in inv:
            rp = inv["replace"]
            t("H3c", "H3", "psalm.function.story", at(full, rp), at(full, re_), better="lower",
              label="replace lowers their function")
            t("H3d", "H3", "psalm.expression.story", at(full, rp), at(full, re_), "non_inferiority",
              margin=mg["psalm.expression.story"], better="lower", label="replace keeps their expression as low as re-invent")
            t("H3e", "H3", "psalm.function.style", at(full, rp), at(full, pr), "non_inferiority",
              margin=mg["psalm.function.style"], better="higher",
              label="the kept style dimensions keep their function under every setting")
    if "paraphrase" in by:
        p = inv.get("preserve") if policies else None
        if p or not policies:
            a, b = at(full, p), at(by["paraphrase"], p)
            for m in (*RETENTION, "salience", "psalm.function.story"):
                t(f"H4.{m}", "H4", m, a, b, "non_inferiority", margin=mg[m], **({"better": "higher"} if m.startswith("psalm") else {}))
            for m in ("ngram8", "span"):
                t(f"H4.{m}", "H4", m, a, b)
            t("H4.psalm.expression.story", "H4", "psalm.expression.story", a, b, better="lower")
            t("H4.span12", "H4", "span", a, test="share_below", value=12, share=0.95)
    if "flat" in by:
        for p in pols:
            for m in RETENTION:
                t(f"H5.{p or 'all'}.{m}", "H5", m, at(full, p), at(by["flat"], p))
            t(f"H5.{p or 'all'}.in_range", "H5", "psalm.in_range", at(full, p), at(by["flat"], p), better="higher")
            t(f"H5.{p or 'all'}.span", "H5", "span", at(full, p), at(by["flat"], p), "non_inferiority", margin=mg["span"])
    return H
