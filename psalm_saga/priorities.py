"""Measure priorities: tell the generation which evaluation measures matter most for a study.

A researcher who studies, say, sentence-length distributions can list those measures (or the
whole `style` group) under `priorities`. By default the list is empty and everything is weighted
equally. Priorities act in two ways, both inside the generation (not afterwards):

1  **Effort.** Stages that serve a prioritised measure work harder: more style-revision rounds
   and a tighter tolerance, a second content-repair round, more leakage-guard rounds (table
   EFFECTS). Priorities only ever raise effort; they never lower a setting.
2  **Weight.** Where a stage chooses between candidate texts, the measures it can compute itself
   (conform: the style features and the sentence- and paragraph-length distributions; review: the
   style distance of a repair) weigh `PRIORITY_WEIGHT` times as much when prioritised, so a
   revision that improves a prioritised measure at the cost of another is preferred, and one that
   hurts a prioritised measure is rejected.

The evaluation reports a priority score (the mean score of the prioritised measures) next to the
others, and suggested fixes for prioritised measures come first.
"""

from __future__ import annotations

from dataclasses import dataclass

PRIORITY_WEIGHT = 3.0


def groups() -> dict[str, list[str]]:
    from psalm_saga.eval.grading import METRICS

    out: dict[str, list[str]] = {}
    for m in METRICS:
        out.setdefault(m.group, []).append(m.key)
    return out


def resolve(priorities: list[str] | None) -> set[str]:
    """Measure keys named directly or through their group."""
    g = groups()
    out: set[str] = set()
    for p in priorities or []:
        out |= set(g.get(p, [p]))
    return out


def weight(priorities: list[str] | None, *metrics: str) -> float:
    """Weight of a quantity that serves these measures: PRIORITY_WEIGHT if any is prioritised."""
    chosen = resolve(priorities)
    return PRIORITY_WEIGHT if chosen and chosen & set(metrics) else 1.0


STYLE = ("style_drift", "sentence_overlap", "paragraph_overlap", "word_overlap", "fw_cosine", "judge_style")
STORY = ("kg_events", "kg_causes", "kg_places", "kg_world", "scenes", "design_coverage", "judge_content",
         "psalm_fidelity", "kg_characters", "kg_social", "salience", "presence", "jaccard")
DISTANCE = ("ngram8", "span", "names", "psalm_expression")


@dataclass(frozen=True)
class Effect:
    metrics: tuple[str, ...]
    stage: str
    param: str
    value: float | int
    op: str  # "max" raises to value, "min" lowers to value
    why: str


EFFECTS: tuple[Effect, ...] = (
    Effect(STYLE, "conform", "rounds", 4, "max", "up to 4 style-revision rounds instead of 2"),
    Effect(STYLE, "conform", "tolerance", 0.06, "min", "style revision continues until within 0.06 of the source"),
    Effect(STYLE, "review", "style_slack", 0.02, "min", "a content repair may loosen the style by at most 0.02"),
    Effect(("pacing", "paragraph_overlap"), "conform", "rounds", 3, "max", "an extra style-revision round"),
    Effect(("length_ratio",), "conform", "max_length_change", 0.08, "min", "style revisions may change the length by 8% at most"),
    Effect(STORY, "review", "rounds", 2, "max", "two content-repair rounds instead of one"),
    Effect(STORY, "review", "strict_coverage", True, "max", "missing places, objects and relations are repaired, not only noted"),
    Effect(DISTANCE, "guard", "rounds", 3, "max", "three rounds of rewording copied passages"),
    Effect(DISTANCE, "guard", "min_span", 8, "min", "copied passages from 8 words are reworded (instead of 10)"),
)


def steered_params(priorities: list[str] | None, stage: str, params: dict) -> dict:
    """The stage's parameters with the effort raised for the prioritised measures."""
    chosen = resolve(priorities)
    if not chosen:
        return params
    out = dict(params)
    for e in EFFECTS:
        if e.stage != stage or not chosen & set(e.metrics):
            continue
        cur = out.get(e.param)
        if cur is None:
            out[e.param] = e.value
        elif e.op == "max":
            out[e.param] = max(cur, e.value)
        else:
            out[e.param] = min(cur, e.value)
    return out


def describe(priorities: list[str] | None) -> list[dict]:
    """What the priorities change, for the interface and the run record."""
    chosen = resolve(priorities)
    seen, out = set(), []
    for e in EFFECTS:
        if chosen & set(e.metrics) and (e.stage, e.param) not in seen:
            seen.add((e.stage, e.param))
            out.append({"stage": e.stage, "param": e.param, "value": e.value, "why": e.why,
                        "for": sorted(chosen & set(e.metrics))})
    if chosen & {"style_drift", "sentence_overlap", "paragraph_overlap"}:
        out.append({"stage": "conform", "param": "weights", "value": PRIORITY_WEIGHT,
                    "why": f"prioritised style quantities weigh {PRIORITY_WEIGHT:g}× when choosing between revisions",
                    "for": sorted(chosen & {"style_drift", "sentence_overlap", "paragraph_overlap"})})
    return out


def priority_score(grades: dict, priorities: list[str] | None) -> dict | None:
    chosen = resolve(priorities)
    if not chosen:
        return None
    vals = [(k, g["score"]) for k, g in grades.items() if k in chosen and g.get("score") is not None and g.get("grade")]
    if not vals:
        return {"score": None, "n": 0, "measures": sorted(chosen)}
    return {"score": round(sum(v for _, v in vals) / len(vals), 3), "n": len(vals), "measures": sorted(chosen),
            "lowest": sorted(vals, key=lambda kv: kv[1])[:3]}
