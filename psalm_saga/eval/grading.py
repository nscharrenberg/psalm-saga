"""What the evaluation numbers mean: one catalogue for the report, the web app and the fixes.

Every metric is listed once with where it lives in evaluation.json, the question it answers,
the instrument it belongs to (docs/EXPERIMENTS.md), and the thresholds that turn it into
green (preserved / safe), orange (borderline: look before relying on it) or red (not
preserved / leaked). Thresholds are provisional working values, to be fixed after a pilot.

Metrics are grouped by the question a researcher asks of the synthetic text. Each group can
carry a fix: which stage to redo and with what instruction. Fixes are for interactive use;
a run revised with its own evaluation no longer has independent measurements, so the run
records it (run.json `evaluation_guided_fixes`) and the datasheet says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Metric:
    """One graded measure.

    The raw value (as computed, in its own unit) is turned into a **score from 0 to 1 where 1 is
    best**, by one of four transformations (`norm`), so that every measure reads the same way:

      unit   s = clamp(x, 0, 1)            the value already is a 0–1 "higher is better" share,
                                           similarity or recall
      corr   s = max(0, r)                 correlations: a negative correlation is as bad as none
      diff   s = max(0, 1 − x / c)         differences and distances (0 = identical), *inverted*;
                                           c is the difference that counts as completely off
      ratio  s = max(0, 1 − |x − 1| / c)   ratios where 1 is ideal (length, variety share)

    The colour follows from the score: green ≥ `s_good` (default 0.80), orange ≥ `s_warn`
    (default 0.60), red below. `scale` (c) is chosen per measure so that these cut-offs fall at
    the raw thresholds stated in `meaning`. Thresholds are provisional, to be fixed after a pilot.
    """

    key: str
    path: str  # dotted path in evaluation.json
    group: str
    label: str
    instrument: str
    meaning: str
    norm: str | None = None  # unit | corr | diff | ratio; None = descriptive, not graded
    scale: float = 1.0
    s_good: float = 0.8
    s_warn: float = 0.6
    fmt: str = "num"  # how to show the raw value: num | pct | int
    raw_unit: str = ""  # name of the raw quantity, for the formula ("D", "r", "drift", ...)
    raw_name: str = ""  # how the stored raw value is labelled, when it differs from what the formula uses

    def score(self, x: float) -> float:
        if self.norm == "unit" or self.norm == "corr":
            s = x
        elif self.norm == "diff":
            s = 1 - x / self.scale
        elif self.norm == "ratio":
            s = 1 - abs(x - 1) / self.scale
        else:
            return float("nan")
        return round(min(1.0, max(0.0, s)), 3)

    @property
    def formula(self) -> str:
        u = self.raw_unit or "x"
        c = f"{self.scale:g}"
        return {"unit": f"score = {u} (already 0–1, higher is better)",
                "corr": f"score = max(0, {u}) (correlation; negative counts as 0)",
                "diff": f"score = max(0, 1 − {u} / {c}) (inverted: {u} = 0 gives 1, the best; {u} ≥ {c} gives 0)",
                "ratio": f"score = max(0, 1 − |{u} − 1| / {c}) (1 is ideal; off by {c} or more → 0)"}.get(self.norm or "", "descriptive, not graded")

    def raw_at(self, s: float) -> float | None:
        """The raw value at which the score equals s (to state the cut-offs in the raw unit)."""
        if self.norm in ("unit", "corr"):
            return s
        if self.norm == "diff":
            return (1 - s) * self.scale
        if self.norm == "ratio":
            return (1 - s) * self.scale  # distance from 1
        return None

    @property
    def rule(self) -> str:
        if not self.norm:
            return ""
        return f"score ≥ {self.s_good:.2f} · ≥ {self.s_warn:.2f} · below"


GROUPS: dict[str, dict[str, str]] = {
    "form": {"title": "Language and form", "question": "Is it the right kind of text — language, variety, form (prose or verse), length?",
             "why": "A corpus of synthetic texts is only a stand-in if each text is in the same language, variety and form, at about the same length."},
    "style": {"title": "Style", "question": "Does the prose behave like the source's prose?",
              "why": "Stylometric and register studies measure exactly these quantities; they must come out the same on the synthetic text."},
    "structure": {"title": "Story structure", "question": "Is the story built the same way — chapters, scenes, events?",
                  "why": "Narratological research (plot, pacing, causality) reads the structure; it must survive the rewriting."},
    "characters": {"title": "Characters", "question": "Are the same kinds of people present, with the same weight and ties?",
                   "why": "Character networks, salience and gender representation are common research targets."},
    "content": {"title": "Content", "question": "Does the synthetic text tell the same story, in the reader's judgement?",
                "why": "Measures miss what a reader sees at once; a judge and the design checklist check the story as told."},
    "distance": {"title": "Protected expression", "question": "Is the source's wording gone?",
                 "why": "The point of the exercise: the synthetic text must not reproduce the source's expression."},
}

METRICS: list[Metric] = [
    Metric("length_ratio", "length.ratio", "form", "length vs target", "G1",
           "Synthetic words ÷ target words. Green within ±10%, orange within ±20%.", "ratio", 0.5, raw_unit="ratio"),
    Metric("retention", "variety.retention", "form", "language variety retained", "F6",
           "Share of dialect / historical forms in the synthetic text ÷ that share in the source (1 = same; above 1 "
           "means the variety is overdone). Green within 0.2 of 1, orange within 0.4.", "ratio", 1.0, raw_unit="retention"),
    Metric("form_match", "form.match", "form", "text form", "F1",
           "Is the synthetic text in the source's form (prose, verse or drama)? 1 = same form, 0 = different.",
           "unit", fmt="int", s_good=1.0, s_warn=1.0, raw_unit="match"),
    Metric("verse_lines", "form.line_words_rel_diff", "form", "verse line length", "F1",
           "Relative difference in words per verse line (0 = identical). Green below 0.15, orange below 0.30.",
           "diff", 0.75, raw_unit="Δ"),
    Metric("verse_stanzas", "form.stanza_rel_diff", "form", "stanza size", "F1",
           "Relative difference in lines per stanza (0 = identical). Green below 0.15, orange below 0.30.",
           "diff", 0.75, raw_unit="Δ"),
    Metric("verse_rhyme", "form.rhyme_share_diff", "form", "rhyme", "F1",
           "Absolute difference in the share of rhyming lines (0 = identical). Green below 0.10, orange below 0.20.",
           "diff", 0.5, raw_unit="Δ"),
    Metric("style_drift", "fidelity.stylometric_mean_rel_diff", "style", "stylometric drift", "F1",
           "Average relative difference over ten style features (0 = identical). Green below 0.10, orange below "
           "0.20 — widened when the source's two halves already differ more (see the rule).", "diff", 0.5,
           raw_unit="drift"),
    Metric("fw_cosine", "fidelity.function_word_cosine", "style", "function-word profile", "F1b",
           "Cosine similarity of the most frequent (mostly function) words, names excluded — what stylometry uses "
           "to recognise a style (1 = identical). Scored on the gap 1 − cosine: green when the gap is below 0.05, "
           "orange below 0.10, widened by the source's own half-to-half gap.", "diff", 0.25, raw_unit="(1 − cosine)",
           raw_name="cosine"),
    Metric("sentence_overlap", "distributions.sentence_length.ks", "style", "sentence-length distribution", "F1",
           "Largest gap between the cumulative distributions of sentence length (Kolmogorov–Smirnov D; 0 = "
           "identical). Green below 0.10, orange below 0.20; also green when the test cannot tell the two apart "
           "(p ≥ 0.05).", "diff", 0.5, raw_unit="D"),
    Metric("paragraph_overlap", "distributions.paragraph_length.ks", "style", "paragraph-length distribution", "F1",
           "Kolmogorov–Smirnov D between paragraph-length distributions (0 = identical). Same rule as sentences.",
           "diff", 0.5, raw_unit="D"),
    Metric("word_overlap", "distributions.word_length.ks", "style", "word-length distribution", "F1",
           "Kolmogorov–Smirnov D between word-length distributions (0 = identical). Same rule as sentences.",
           "diff", 0.5, raw_unit="D"),
    Metric("pacing", "fidelity.pacing_profile_r", "structure", "pacing profile", "F2",
           "Do sentence length and the amount of direct speech rise and fall at the same points of the story? "
           "Correlation over chapters, or over parts of the text for texts with fewer than three chapters.",
           "corr", s_good=0.7, s_warn=0.5, raw_unit="r"),
    Metric("chapter_count", "fidelity.chapter_count_match", "structure", "chapter count", "F2",
           "Does the synthetic text have as many chapters (or poems) as the source? 1 = same, 0 = different.",
           "unit", fmt="int", s_good=1.0, s_warn=1.0, raw_unit="match"),
    Metric("chapter_r", "fidelity.chapter_length_pearson", "structure", "chapter-length profile", "F2",
           "Correlation of chapter lengths: do long chapters stay long and short ones short?", "corr", raw_unit="r"),
    Metric("scenes", "fidelity.scenes_per_chapter_match", "structure", "scenes per chapter", "F2",
           "Share of chapters with the same number of scenes as the source.", "unit", s_good=0.9, s_warn=0.7,
           fmt="pct", raw_unit="share"),
    Metric("kg_events", "kg.events.value", "structure", "events realised", "KG",
           "Share of the source's events found when the synthetic text is analysed the same way, relative to how "
           "many the analysis finds again in the source itself (its ceiling).", "unit", fmt="pct", raw_unit="recall"),
    Metric("kg_causes", "kg.causes.value", "structure", "causal links realised", "KG",
           "Share of the source's cause → effect links found in the synthetic text (relative to the ceiling).",
           "unit", s_good=0.7, s_warn=0.5, fmt="pct", raw_unit="recall"),
    Metric("kg_places", "kg.places.value", "structure", "places realised", "KG",
           "Share of the source's places that have a counterpart in the synthetic text (relative to the ceiling).",
           "unit", fmt="pct", raw_unit="recall"),
    Metric("kg_world", "kg.world.value", "structure", "ties to places and objects", "KG",
           "Share of the source's ties between entities and places, objects or organisations (lives in, owns, "
           "member of) found in the synthetic text (relative to the ceiling).", "unit", s_good=0.7, s_warn=0.5,
           fmt="pct", raw_unit="recall"),
    Metric("salience", "fidelity.characters.salience_spearman", "characters", "character salience", "F3",
           "Do the same characters matter most, in the same order? (rank correlation of mentions)", "corr", raw_unit="ρ"),
    Metric("presence", "fidelity.characters.chapter_presence_pearson", "characters", "presence per chapter", "F3",
           "Is each character present in the same chapters, to the same degree?", "corr", s_good=0.7, s_warn=0.5,
           raw_unit="r"),
    Metric("jaccard", "fidelity.characters.cooccurrence_jaccard", "characters", "who meets whom", "F3",
           "Share of character pairs sharing a chapter in either text that do so in both.", "unit", s_good=0.7,
           s_warn=0.5, raw_unit="Jaccard"),
    Metric("kg_characters", "kg.characters.value", "characters", "characters realised", "KG",
           "Share of the source's characters found in the synthetic text by the same analysis (relative to the "
           "ceiling).", "unit", s_good=0.9, s_warn=0.7, fmt="pct", raw_unit="recall"),
    Metric("kg_social", "kg.social.value", "characters", "relationships realised", "KG",
           "Share of the source's relationships between characters found in the synthetic text (relative to the "
           "ceiling).", "unit", s_good=0.7, s_warn=0.5, fmt="pct", raw_unit="recall"),
    Metric("gender_mentions", "fidelity.gender.female_mention_share.abs_diff", "characters",
           "women's share of mentions", "F7", "Difference in the share of character mentions that refer to women "
           "(0 = same). Green below 3 points, orange below 6.", "diff", 0.15, fmt="pct", raw_unit="Δ"),
    Metric("gender_pronouns", "fidelity.gender.female_pronoun_share.abs_diff", "characters",
           "feminine pronoun share", "F7", "Difference in the share of gendered pronouns that are feminine "
           "(0 = same). Green below 3 points, orange below 6.", "diff", 0.15, fmt="pct", raw_unit="Δ"),
    Metric("design_coverage", "coverage.share", "content", "design facts shown", "C1",
           "Share of the design checklist (each chapter's events, causal links, relations and places/objects) "
           "that the reviewer found realised in the final chapters.", "unit", fmt="pct", raw_unit="share"),
    Metric("judge_content", "judges.content.score", "content", "same story (judge)", "J1",
           "An LLM judge, given the source's and the synthetic text's chapter summaries side by side, rates how "
           "far the synthetic text tells the same story (events, order, outcome, who does what) on a 1–5 scale; "
           "score = (rating − 1) / 4.", "unit", raw_unit="score"),
    Metric("psalm_fidelity", "judges.psalm.fidelity", "content", "dimension fidelity (PSALM judge)", "J3",
           "The PSALM judge compares the two texts on the six dimensions and 36 sub-dimensions, citing evidence from both "
           "and arguing each verdict; this is the mean FUNCTION similarity (does the synthetic text do the same thing?) "
           "over the dimensions the policy does not replace; ratings 1–5 become (rating − 1) / 4.", "unit",
           raw_unit="score"),
    Metric("judge_style", "judges.style.score", "content", "same style (judge)", "J2",
           "An LLM judge compares an excerpt of each text (names masked) and rates how similar the writing is "
           "in voice, register, rhythm and imagery on a 1–5 scale; score = (rating − 1) / 4.", "unit",
           raw_unit="score"),
    Metric("psalm_expression", "judges.psalm.appropriation", "distance", "concrete expression kept (PSALM judge)", "J3",
           "Where the policy asks for change (re-invented or replaced dimensions), how far the synthetic text still keeps "
           "the source's concrete particulars — traits, events, images, settings, phrasing — per the PSALM judge's "
           "expression ratings on the identifying (surface) aspects. Scored inverted: 0 similarity gives 1. Green below "
           "0.20 similarity, orange below 0.40.", "diff", 1.0, raw_unit="similarity"),
    Metric("ngram8", "leakage.ngram8_overlap", "distance", "8-word overlap", "D1",
           "Share of the synthetic text's 8-word sequences that also occur in the source. Green below 0.2%, "
           "orange below 0.4%.", "diff", 0.01, fmt="pct", raw_unit="overlap"),
    Metric("span", "leakage.longest_copied_span_words", "distance", "longest copied passage", "D1",
           "Longest word-for-word passage shared with the source, in words. Green up to 8 words, orange up to 16.",
           "diff", 40, fmt="int", raw_unit="words"),
    Metric("names", "leakage.names_leaked", "distance", "original names left", "D2",
           "Original names (or aliases) still present in the synthetic text. Any leaked name is red.", "diff", 5,
           s_good=0.99, s_warn=0.99, fmt="int", raw_unit="names"),
    Metric("jsd", "divergence.char3_jsd", "distance", "letter-pattern divergence", "D4",
           "Jensen–Shannon divergence of character trigrams, names masked (0 = same patterns). Descriptive, not "
           "graded: too low means a near-copy, too high means the style was lost; compare across conditions."),
]
BY_KEY = {m.key: m for m in METRICS}

# A compact core for experiments: one or two measures per question, chosen to be robust on short
# and long texts and not redundant with each other. Everything else stays in the report as
# supporting detail (see docs/EXPERIMENTS.md).
CORE = ("length_ratio", "form_match", "style_drift", "sentence_overlap", "kg_events", "kg_causes", "kg_characters",
        "salience", "design_coverage", "judge_content", "psalm_fidelity", "ngram8", "span", "names")


def lookup(report: dict, path: str) -> Any:
    cur: Any = report
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def color(m: Metric, s: float | None) -> str:
    if s is None or not m.norm or s != s:  # nan
        return ""
    return "good" if s >= m.s_good else "warn" if s >= m.s_warn else "bad"


def grade(m: Metric, v: Any) -> str:
    """Colour of a raw value (kept for callers that grade single values)."""
    if v is None or isinstance(v, bool) or not isinstance(v, int | float) or not m.norm:
        return ""
    return color(m, m.score(float(v)))


DIST_KEYS = ("sentence_overlap", "paragraph_overlap", "word_overlap")


def grades(report: dict) -> dict[str, dict]:
    """Per measure: raw `value`, normalised `score` (0–1, 1 = best), `grade` (good | warn | bad,
    "" when descriptive), the `formula` that turned the value into the score, and the `rule`."""
    out = {}
    variety_kept = (report.get("variety") or {}).get("target") == "kept"
    na = report.get("not_measurable") or {}
    base = report.get("self_agreement") or {}
    for m in METRICS:
        v = lookup(report, m.path)
        if v is None or isinstance(v, bool) or not isinstance(v, int | float) \
                or str(na.get(m.key, "")).startswith("not applicable: the source is"):
            continue
        x = float(v)
        formula, note = m.formula, ""
        if m.key == "fw_cosine":
            x = 1 - x  # scored on the gap to identical
        if m.key == "style_drift" and base.get("style_drift") is not None:
            # relative to the author's own consistency: the first half of the source against its second
            b = float(base["style_drift"])
            allow = max(0.0, b - 0.05)
            x = max(0.0, x - allow)
            formula = f"score = max(0, 1 − max(0, drift − {allow:.2f}) / 0.5) (inverted; {allow:.2f} = source's own half-to-half drift {b:.2f} − 0.05)"
            note = f"source vs itself: {b:.2f}"
        if m.key == "fw_cosine" and base.get("function_word_cosine") is not None:
            b = float(base["function_word_cosine"])
            allow = max(0.0, (1 - b) - 0.03)
            x = max(0.0, x - allow)
            formula = (f"score = max(0, 1 − max(0, (1 − cosine) − {allow:.2f}) / 0.25) (inverted gap; {allow:.2f} = "
                       f"source's own half-to-half gap {1 - b:.2f} − 0.03)")
            note = f"source vs itself: {b:.2f}"
        s = m.score(x) if m.norm else None
        if m.key in DIST_KEYS and s is not None and s < m.s_good:
            # A gap that a two-sample test cannot tell from chance at these sample sizes is not a difference.
            p = lookup(report, m.path.rsplit(".", 1)[0] + ".ks_p")
            if p is not None and p >= 0.05:
                s = max(s, m.s_good)
                formula += f"; raised to {m.s_good:.2f} because the difference is not statistically detectable (p = {p:.2f})"
        g = color(m, s)
        if m.key == "retention" and not variety_kept:
            g = ""  # modernised on purpose: no target
        rule = m.rule + (f" ({note})" if note else "")
        out[m.key] = {"value": v, "score": s, "grade": g, "formula": formula, "rule": rule}
    return out


def summary_scores(report: dict, keys: tuple[str, ...] = CORE) -> dict:
    """Mean normalised score per question, over the core measures that could be computed."""
    g = grades(report)
    by: dict[str, list[float]] = {}
    for k in keys:
        if k in g and g[k]["score"] is not None and g[k]["grade"]:
            by.setdefault(BY_KEY[k].group, []).append(g[k]["score"])
    return {grp: round(sum(v) / len(v), 3) for grp, v in by.items()}


def catalogue() -> dict:
    """For the web app: groups and metric definitions (labels, meanings, formulas, thresholds)."""
    return {"groups": GROUPS, "core": list(CORE),
            "metrics": [{**m.__dict__, "formula": m.formula, "rule": m.rule, "core": m.key in CORE,
                         "raw_good": m.raw_at(m.s_good), "raw_warn": m.raw_at(m.s_warn)} for m in METRICS]}


# ------------------------------------------------------------------ fixes


@dataclass
class Fix:
    id: str
    group: str
    title: str
    explanation: str
    rerun_from: str
    overrides: dict[str, Any] = field(default_factory=dict)
    cost: str = ""
    metrics: list[str] = field(default_factory=list)
    severity: str = "bad"  # bad: a red measure; warn: only orange — may be within run-to-run noise
    scores: dict[str, Any] = field(default_factory=dict)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


def suggest_fixes(report: dict, config: dict | None = None) -> list[dict]:
    """Targeted fixes for what came out orange or red. Each is applied as a new version of the run
    (psalm_saga.fixes), redoing the work from the stage named; instructions are specific (the design
    items that were missing, the words out of line) rather than generic, and the cheapest stage that
    can fix a problem is preferred: style and variety are fixed by the style-matching stage alone,
    without rewriting the content."""
    g = grades(report)
    ctx = report.get("fix_context") or {}
    miss = ctx.get("missing") or {}
    fixes: list[Fix] = []

    def hit(*keys: str) -> tuple[list[str], str]:
        ks = [k for k in keys if k in g and g[k]["grade"] in ("warn", "bad")]
        return ks, ("bad" if any(g[k]["grade"] == "bad" for k in ks) else "warn")

    def add(f: Fix) -> None:
        f.scores = {k: g[k]["score"] for k in f.metrics if k in g}
        fixes.append(f)

    m, sev = hit("ngram8", "span", "names")
    if m:
        add(Fix("leakage", "distance", "Remove the remaining overlap",
                "Run the copy guard again with a stricter threshold (shared passages of 8 words instead of 10) and more "
                "rounds. Only the affected paragraphs are rewritten; names are replaced from the rename table.",
                "guard", {"stages.guard.params.min_span": 8, "stages.guard.params.rounds": 3},
                "cheap: only flagged paragraphs", m, sev))
    m, sev = hit("style_drift", "sentence_overlap", "paragraph_overlap", "word_overlap", "retention")
    if m:
        add(Fix("style", "style", "Match the source's style more closely",
                "Run the style-matching stage again with more revision rounds and a tighter tolerance. It measures each "
                "chapter (sentence lengths and their spread, paragraphs, dialogue, punctuation, dialect or historical "
                "forms) and revises rhythm and layout towards the source, keeping a revision only if it gets closer. "
                "The content is not rewritten.",
                "conform", {"stages.conform.params.rounds": 4, "stages.conform.params.tolerance": 0.06,
                            "stages.conform.params.max_length_change": 0.15},
                "moderate: up to four revisions per chapter, then review and evaluation", m, sev))
    m, sev = hit("fw_cosine")
    if m:
        gaps = __import__("psalm_saga.fixes", fromlist=["function_word_gaps"]).function_word_gaps(
            (report.get("distributions") or {}).get("function_words") or [])
        if gaps:
            add(Fix("wordhabits", "style", "Redraft with the source's word habits",
                    "Redraft every chapter, telling the writer which frequent (mostly function) words it over- or "
                    "under-uses compared with the source — the pattern stylometry recognises a style by.",
                    "draft", {"stages.draft.params.fix_instruction":
                              "Match the source's habits in frequent words. In the previous version these were most out of "
                              "line (aim for the source's rate, without forcing them where they do not fit):\n" + _bullets(gaps)},
                    "expensive: redrafts all chapters", m, sev))
    m, sev = hit("length_ratio", "chapter_r")
    if m:
        ratio = (report.get("length") or {}).get("ratio") or 1
        add(Fix("length", "form", "Redraft to the planned lengths",
                f"Redraft with each chapter held to its word budget; the previous version was "
                f"{abs(round(100 * (ratio - 1)))}% {'too long' if ratio > 1 else 'too short'}.",
                "draft", {"stages.draft.params.fix_instruction":
                          f"The previous version was {abs(round(100 * (ratio - 1)))}% {'longer' if ratio > 1 else 'shorter'} "
                          "than planned. Keep each chapter within 10% of its stated word budget: "
                          + ("tell the beats more economically." if ratio > 1 else "develop the beats more fully."),
                          "stages.draft.params.top_up": True}, "expensive: redrafts all chapters", m, sev))
    m, sev = hit("scenes", "kg_events", "kg_causes", "kg_places", "design_coverage", "judge_content")
    if m:
        items = [*(f"event — {x}" for x in miss.get("events", [])), *(f"cause — {x}" for x in miss.get("causes", [])),
                 *(f"place — {x}" for x in miss.get("places", []))][:16]
        add(Fix("structure", "structure", "Re-plan so the missing story elements happen",
                "Plan again and redraft, naming the design's events, causal links and places that the analysis did not "
                f"find in the previous version{f' ({len(items)} listed)' if items else ''}.",
                "plan", {"stages.plan.params.fix_instruction":
                         ("Keep the skeleton's scenes one-to-one and make every skeleton event happen. In the previous version "
                          "these design elements were missing or not recognisable; make sure each one visibly happens:\n"
                          + _bullets(items)) if items else
                         "Keep the skeleton's scenes one-to-one (same number and order), make every skeleton event happen, keep "
                         "each scene's setting, and make each cause visibly lead to its effect."},
                "expensive: re-plans and redrafts everything", m, sev))
    m, sev = hit("salience", "presence", "jaccard", "kg_characters", "kg_social", "kg_world")
    if m:
        items = [*(f"character — {x}" for x in miss.get("characters", [])),
                 *(f"relation — {x}" for x in miss.get("relations", []))][:16]
        add(Fix("characters", "characters", "Re-plan with the missing characters and relationships",
                "Plan again and redraft, naming the characters and relationships of the design that the analysis did not "
                f"find in the previous version{f' ({len(items)} listed)' if items else ''}.",
                "plan", {"stages.plan.params.fix_instruction":
                         ("Keep the cast of every scene as in the skeleton. In the previous version these characters or "
                          "relationships were missing or not recognisable; let each one appear and show:\n" + _bullets(items))
                         if items else "Keep the cast of every scene exactly as in the skeleton, and let the relationships "
                                       "between them show. Do not drop or add recurring characters."},
                "expensive: re-plans and redrafts everything", m, sev))
    m, sev = hit("gender_mentions", "gender_pronouns")
    if m:
        gl = ctx.get("genders") or []
        lst = "; ".join(f"{x['name']}: {x['gender']}" for x in gl)
        add(Fix("gender", "characters", "Redraft keeping every character's gender",
                "Redraft with each main character's gender stated, so that pronouns and forms of address follow the design "
                "(the renaming itself is kept).",
                "draft", {"stages.draft.params.fix_instruction":
                          ("Keep each character's gender consistently, in pronouns and forms of address: " + lst + ".") if lst else
                          "Keep each character's gender exactly as in the cast notes, in pronouns and forms of address."},
                "expensive: redrafts all chapters", m, sev))
    return [f.__dict__ for f in fixes]
