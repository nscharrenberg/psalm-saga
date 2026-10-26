"""Automatic, model-free evaluation of one run: the evidence behind the claim
"same data points, none of the protected expression".

Fidelity (should be HIGH): structure, length profile, stylometrics, character
salience and co-occurrence network, measured on the source and on the synthetic text
with the same code. Distance (should be HIGH, i.e. leakage LOW): verbatim n-gram
overlap, copied spans, surviving original names.
"""

from __future__ import annotations

import re
from itertools import combinations

from psalm_saga.artifacts import Bible, ChapterDraft, LanguageVariety, Plan, Spec, TransformMap
from psalm_saga.eval.features import (
    bible_characters,
    char_ngram_jsd,
    distribution_report,
    function_word_cosine,
    gender_shares,
    name_tokens,
    proper_noun_tokens,
    style_profile,
)
from psalm_saga.store import RunStore
from psalm_saga.text.chunking import split_chapters, word_count
from psalm_saga.text.form import form_metrics
from psalm_saga.text.language import detect_language
from psalm_saga.text.metrics import leakage_report, mention_counts, pearson, spearman, stylometrics
from psalm_saga.text.style import layout_reliable
from psalm_saga.text.variety import variety_share

STYLE_KEYS = [
    "mean_sentence_words", "sd_sentence_words", "mean_paragraph_words", "mean_word_chars", "mattr_500",
    "dialogue_word_share", "question_sentence_share", "commas_per_1k", "first_person_per_1k", "third_person_per_1k",
]


def _rel(a: float, b: float) -> float:
    """Symmetric relative difference in [0, 1]; 0 = identical."""
    a, b = a or 0.0, b or 0.0
    return abs(a - b) / max(abs(a), abs(b)) if (a or b) else 0.0


def _chapters(store: RunStore) -> list[ChapterDraft]:
    ds = [ChapterDraft.model_validate_json(p.read_text(encoding="utf-8")) for p in store.glob("chapters/ch_*.json")]
    return sorted(ds, key=lambda d: d.index)


MIN_CHAPTERS_R = 5  # a correlation over fewer points is too unstable to grade
MIN_UNIT_MENTIONS = 5  # mentions per unit (chapter or segment) for presence to correlate
MIN_PAIRS = 3  # character pairs sharing a unit in the source, for co-occurrence overlap


def character_fidelity(src_chapters: list[str], syn_chapters: list[str], bible: Bible, mapping: dict[str, str], top_k: int = 12,
                       min_mentions: int = 3) -> dict:
    chars = [e for e in bible.characters() if e.mentions >= min_mentions][:top_k]
    rows = []
    for e in chars:
        src_names = [e.name, *e.aliases]
        # Renamed forms map through the table; descriptions ("de weduwe") are not renamed and are
        # looked for as they are.
        syn_names = sorted({mapping.get(n, n) for n in src_names})
        if not syn_names:
            continue
        rows.append((e.name, [mention_counts(t, src_names) for t in src_chapters], [mention_counts(t, syn_names) for t in syn_chapters]))
    if not rows:
        return {"characters_compared": 0}
    if len(rows) < 3:  # with one or two characters, presence and co-occurrence are degenerate (0 or 1)
        return {"characters_compared": len(rows), "per_character": {name: {"source": s, "synthetic": y} for name, s, y in rows}}
    n = min(len(src_chapters), len(syn_chapters))
    # Presence needs counts large enough to correlate: merge neighbouring units until they hold on
    # average MIN_UNIT_MENTIONS mentions of the compared characters (at least 3 units remain).
    mentions = sum(sum(r[1][:n]) for r in rows)
    k = n if mentions / max(n, 1) >= MIN_UNIT_MENTIONS else max(3, int(mentions // MIN_UNIT_MENTIONS))
    if k < n:
        def merge(v: list[int]) -> list[int]:
            size = n / k
            return [sum(v[int(i * size): int((i + 1) * size)]) for i in range(k)]
        rows = [(name, merge(s[:n]), merge(y[:n])) for name, s, y in rows]
        n = k
    totals_src = [sum(r[1]) for r in rows]
    totals_syn = [sum(r[2]) for r in rows]
    flat_src = [v for r in rows for v in r[1][:n]]
    flat_syn = [v for r in rows for v in r[2][:n]]

    def edges(idx: int) -> set[tuple[str, str]]:
        out = set()
        for ch in range(n):
            present = [r[0] for r in rows if r[idx][ch] > 0]
            out |= {tuple(sorted(p)) for p in combinations(present, 2)}
        return out

    es, ey = edges(1), edges(2)
    union = es | ey
    enough = mentions >= 3 * MIN_UNIT_MENTIONS
    return {
        "characters_compared": len(rows),
        "units": n,
        "mentions": mentions,
        "salience_spearman": _round(spearman(totals_src, totals_syn)),
        "chapter_presence_pearson": _round(pearson([float(x) for x in flat_src], [float(x) for x in flat_syn])) if enough else None,
        # with one or two pairs in play, the overlap can only be 0, 0.5 or 1
        "cooccurrence_jaccard": round(len(es & ey) / len(union), 3) if len(es) >= MIN_PAIRS else None,
        "source_pairs": len(es),
        "per_character": {name: {"source": s, "synthetic": y} for name, s, y in rows},
    }


# Measures that presuppose a story with characters, scenes and events.
NARRATIVE_KEYS = ("salience", "presence", "jaccard", "kg_characters", "kg_social", "kg_events", "kg_causes", "scenes",
                  "gender_mentions")


def _kind_phrase(kind: dict) -> str:
    return {"essay": "an essay", "letters": "a collection of letters", "poetry": "a poem or poems", "drama": "a play",
            "other": "not a narrative"}.get(kind.get("kind", ""), "not a narrative")


KG_PARTS = {"characters": ("nodes", "character"), "places": ("nodes", "place"), "events": ("nodes", "event"),
            "causes": ("edges", "causes"), "social": ("edges", "relation:social"), "world": ("edges", "relation:world")}


def kg_scores(summary: dict, ceiling: dict | None) -> dict:
    """Recall of the source's graph in the synthetic text's graph, and — when the source was analysed
    twice — relative to the extractor's agreement with itself. Two analyses of the *same* text do not
    agree perfectly (a scene split differently, an event phrased as two), so raw recall understates
    fidelity; recall ÷ self-agreement is the share of what the instrument can detect at all."""
    out = {}
    for key, (part, typ) in KG_PARTS.items():
        c = (summary.get(part) or {}).get(typ) or {}
        r = c.get("recall")
        if r is None:
            continue
        row = {"recall": r, "found": c.get("kept", 0) + c.get("changed", 0),
               "of": c.get("kept", 0) + c.get("changed", 0) + c.get("source_only", 0)}
        ceil = ((ceiling or {}).get(part) or {}).get(typ, {}).get("recall") if ceiling else None
        if ceil:
            row["ceiling"] = ceil
            row["relative"] = round(min(1.0, r / ceil), 3)
        row["value"] = row.get("relative", r)
        if ceiling and not ceil and row["of"]:
            # The source analysed twice did not find these items again: the extractor cannot see them
            # reliably in this text, so a low recall says nothing about the synthetic text.
            row["ceiling"] = 0.0
            row["value"] = None
        out[key] = row
    return out


def self_agreement(source: str, language: str, exclude: set[str]) -> dict:
    """How close the source is to itself: its first half against its second half (split at a
    sentence boundary), with the same measures used for source vs synthetic. No synthetic text can
    be expected to match the source more closely than the author's two halves match each other, so
    style grades are set relative to these values. Halves hold half the text each, so this baseline
    is, if anything, lenient."""
    from psalm_saga.text.metrics import sentences as _sentences

    sents = _sentences(source)
    lines = [ln for ln in source.splitlines() if ln.strip()]
    if len(sents) >= 20:
        half = len(sents) // 2
        a, b = " ".join(sents[:half]), " ".join(sents[half:])
    elif len(lines) >= 20:  # verse: few sentences, many lines; split at a stanza break near the middle
        blocks = [b for b in re.split(r"\n\s*\n", source.strip()) if b.strip()]
        acc, cut = 0, len(blocks) // 2
        for i, bl in enumerate(blocks):
            acc += len([ln for ln in bl.splitlines() if ln.strip()])
            if acc >= len(lines) / 2:
                cut = i + 1
                break
        if not 0 < cut < len(blocks):
            return {}
        a, b = "\n\n".join(blocks[:cut]), "\n\n".join(blocks[cut:])
    else:
        return {}
    sa, sb = stylometrics(a, language), stylometrics(b, language)
    keys = [k for k in STYLE_KEYS if k in sa and k != "mean_paragraph_words"]
    return {"style_drift": round(sum(_rel(sa.get(k, 0), sb.get(k, 0)) for k in keys) / len(keys), 3),
            "function_word_cosine": _round(function_word_cosine(a, b, exclude)),
            "char3_jsd": _round(char_ngram_jsd(a, b, set()))}


def segments(text: str, k: int = 10) -> list[str]:
    """k consecutive parts of equal word length: the unit of comparison for texts with fewer than
    three chapters, so that presence, co-occurrence and pacing are measurable for any text."""
    toks = text.split()
    if not toks:
        return []
    size = max(1, -(-len(toks) // k))
    return [" ".join(toks[i : i + size]) for i in range(0, len(toks), size)]


_QUOTE = re.compile(r"[\"“”„«»‘’]|(?:^|\s)'|'(?:\s|$)")


def varies_beyond_chance(groups: list[list[float]], n_perm: int = 300, alpha: float = 0.05) -> bool:
    """Permutation test: is the spread of the group means larger than when the same values are
    shuffled across groups of the same sizes?"""
    import random

    vals = [v for g in groups for v in g]
    sizes = [len(g) for g in groups]
    if len(groups) < 3 or min(sizes, default=0) < 2 or len(set(vals)) < 2:
        return False

    def spread(gs):
        means = [sum(g) / len(g) for g in gs]
        m = sum(means) / len(means)
        return sum((x - m) ** 2 for x in means)

    obs = spread(groups)
    rng = random.Random(0)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(vals)
        it, gs = 0, []
        for sz in sizes:
            gs.append(vals[it:it + sz])
            it += sz
        hits += spread(gs) >= obs
    return (hits + 1) / (n_perm + 1) < alpha


def pacing_profile(src_units: list[str], syn_units: list[str], language: str, min_sentences: int = 8) -> tuple[float | None, str]:
    """Do the two texts move the same way through the story? Pearson r between the per-unit
    profiles (mean sentence length and share of words in direct speech, each z-scored). Units are
    merged until each holds enough sentences for a stable mean, and a profile that is flat in the
    source (no dialogue anywhere, say) is left out rather than compared as noise."""
    from psalm_saga.text.metrics import sentences as _sentences

    n = min(len(src_units), len(syn_units))
    if n < 3:
        return None, "fewer than 3 units to compare"
    per_unit = min(len(_sentences(" ".join(src_units[:n]))), len(_sentences(" ".join(syn_units[:n])))) / n
    k = n if per_unit >= min_sentences else max(3, int(per_unit * n // min_sentences))
    if k < 3:
        return None, "too few sentences for 3 units with stable means"

    def regroup(units):
        size = n / k
        return [" ".join(units[int(i * size) : int((i + 1) * size)]) for i in range(k)]

    def series(units):
        st = [stylometrics(u, language) for u in regroup(units[:n])]
        return [s.get("mean_sentence_words", 0.0) for s in st], [s.get("dialogue_word_share", 0.0) for s in st]

    def z(v):
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
        return [(x - m) / sd for x in v] if sd else None

    sa, sb = series(src_units)
    ya, yb = series(syn_units)
    # Which of the source's series move more than chance would? Sentences shuffled across the
    # units (sizes kept): if the real between-unit variation is not larger than that, the source
    # has no pace to follow in this series, and correlating it would grade noise.
    groups = [_sentences(u) for u in regroup(src_units[:n])]
    live = [varies_beyond_chance([[float(len(x.split())) for x in g] for g in groups]),
            varies_beyond_chance([[1.0 if _QUOTE.search(x) else 0.0 for x in g] for g in groups])]
    xs, ys = [], []
    for (a, b), ok in zip(((sa, ya), (sb, yb)), live, strict=True):
        za, zb = z(a), z(b)
        if za is None or not ok:  # flat in the source (or only noise): nothing to follow
            continue
        xs += za
        ys += zb if zb is not None else [0.0] * len(za)
    if not xs:
        return None, ("not applicable: the source's pace (sentence length, dialogue) does not vary across the text "
                      "more than chance would, so there is no profile to follow")
    r = pearson(xs, ys)
    if r is None:  # the synthetic text is flat where the source moves (no dialogue at all, say)
        return 0.0, "the synthetic text does not vary where the source does (for example, it has no dialogue)"
    return _round(r), ""


def pacing_profile_r(src_units: list[str], syn_units: list[str], language: str, min_sentences: int = 8) -> float | None:
    return pacing_profile(src_units, syn_units, language, min_sentences)[0]




def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def variety_report(source: str, story: str, detected: LanguageVariety | None, target: LanguageVariety | None) -> dict:
    """Did the synthetic text keep the source's language variety (dialect, historical spelling)?"""
    if not detected or detected.standard:
        return {"source_variety": "standard", "applicable": False}
    src, syn = variety_share(source, detected), variety_share(story, detected)
    out = {"source_variety": detected.name, "scope": detected.scope, "markers": len(detected.markers),
           "target": "kept" if target and not target.standard else "modernised (by configuration)",
           "applicable": bool(src and src["share"] is not None),
           "source_share": src["share"] if src else None, "synthetic_share": syn["share"] if syn else None}
    if out["applicable"] and out["synthetic_share"] is not None and out["source_share"]:
        out["retention"] = round(out["synthetic_share"] / out["source_share"], 3)
        out["standard_forms_in_synthetic"] = syn.get("top_standard_forms", [])
    return out


def missing_reasons(report: dict, language: str) -> dict[str, str]:
    """Why a measure has no value, keyed like the web app's metrics, so "not measurable" is never
    mistaken for a failure or a bug."""
    out: dict[str, str] = {}
    f = report.get("fidelity") or {}
    if not f:
        return out
    cc = f.get("chapter_count") or {}
    if f.get("chapter_length_pearson") is None:
        out["chapter_r"] = ("chapter counts differ, so chapters cannot be paired"
                                         if cc.get("source") != cc.get("synthetic") else
                                         f"not applicable: fewer than {MIN_CHAPTERS_R} chapters, too few points for a correlation (see the pacing profile)" if (cc.get("source") or 0) < MIN_CHAPTERS_R else
                                         "chapter lengths do not vary")
    if f.get("pacing_profile_r") is None:
        out["pacing"] = f.get("pacing_note") or "too little text for a pacing profile"
    if f.get("scenes_per_chapter_match") is None:
        out["scenes"] = "no scene structure was extracted or planned"
    ch = f.get("characters") or {}
    n = ch.get("characters_compared", 0)
    why = ("not applicable: no character recurs often enough to compare" if not n else
           f"not applicable: the story has fewer than 3 recurring characters (found {n})" if n < 3 else "")
    for k, key in (("salience_spearman", "salience"), ("chapter_presence_pearson", "presence"),
                   ("cooccurrence_jaccard", "jaccard")):
        if ch.get(k) is None:
            out[key] = why or (
                f"not applicable: {ch.get('mentions', 0)} mentions of the main characters in the source, too few to follow "
                f"them through the text (needs {3 * MIN_UNIT_MENTIONS})" if k == "chapter_presence_pearson" else
                f"not applicable: only {ch.get('source_pairs', 0)} pair(s) of characters share a "
                f"{'chapter' if f.get('comparison_unit') == 'chapters' else 'part of the text'} in the source; the overlap "
                f"needs at least {MIN_PAIRS}" if k == "cooccurrence_jaccard" else
                "mention counts do not vary")
    if f.get("function_word_cosine") is None:
        out["fw_cosine"] = "too little text after excluding names"
    g = f.get("gender") or {}
    m = g.get("female_mention_share") or {}
    if m.get("source") is None or m.get("synthetic") is None:
        out["gender_mentions"] = ("not applicable: fewer than 10 mentions of characters with a known gender"
                                  + (" in the source" if m.get("source") is None else " in the synthetic text"))
    pr = g.get("female_pronoun_share")
    if pr is None:
        out["gender_pronouns"] = f"not applicable: not measured for this language ({language}), its pronouns are too ambiguous"
    elif pr.get("source") is None or pr.get("synthetic") is None:
        out["gender_pronouns"] = "not applicable: fewer than 20 gendered pronouns, too few for a stable share"
    st = report.get("structure")
    kg = {"kg_characters": ("nodes", "character"), "kg_places": ("nodes", "place"), "kg_events": ("nodes", "event"),
          "kg_social": ("edges", "relation:social"), "kg_causes": ("edges", "causes"), "kg_world": ("edges", "relation:world")}
    for key, (part, typ) in kg.items():
        if not st:
            out[key] = "the synthetic text has not been analysed with the source's extractor yet (stage recover)"
        elif (row := (report.get("kg") or {}).get(key[3:])) and row.get("value") is None and row.get("ceiling") == 0.0:
            out[key] = (f"not measurable on this text: analysing the source a second time found none of its {row['of']} "
                        f"{'relationships' if typ.startswith('relation') else typ + 's' if not typ.endswith('s') else typ} again, "
                        "so the extractor cannot see them reliably here; a low score would say nothing about the synthetic text")
        elif ((st.get(part) or {}).get(typ) or {}).get("recall") is None:
            label = {"character": "characters", "place": "places", "event": "events",
                     "relation:social": "relationships between characters", "causes": "causal links",
                     "relation:world": "ties to places and objects"}[typ]
            out[key] = f"the source analysis found no {label} to look for"
    v = report.get("variety") or {}
    if not v.get("applicable"):
        out["retention"] = ("the source is written in the standard language" if v.get("source_variety") == "standard"
                            else "too few variety markers to measure")
    cov = report.get("coverage") or {}
    if cov.get("share") is None:
        out["design_coverage"] = ("the review step did not run with the design checklist (stages.review.params.coverage)"
                                  if not cov.get("chapters") else "the reviewer did not answer the checklist")
    jd = report.get("judges") or {}
    off = ("the judges are off: they are optional and best run on a model of another family — enable them for a new "
           "run, or use “Run the judges” on this evaluation")
    for key, part in (("judge_content", "content"), ("judge_style", "style")):
        j = jd.get(part) or {}
        if j.get("score") is None:
            out[key] = j.get("reason_missing") or (off if not jd else "this judge was not selected")
    ps = jd.get("psalm") or {}
    if ps.get("fidelity") is None:
        out["psalm_fidelity"] = ps.get("reason_missing") or (off if not jd else "this judge was not selected")
    if ps.get("appropriation") is None:
        out["psalm_expression"] = (ps.get("reason_missing_appropriation") or ps.get("reason_missing")
                                   or (off if not jd else "this judge was not selected"))
    return out


def coverage_report(store: RunStore) -> dict:
    """Design checklist coverage from the review step (final state of every chapter)."""
    rows = [store.read_json(f"reviews/{p.name}") for p in sorted(store.glob("reviews/ch_*.json"))]
    covs = [r.get("coverage") for r in rows if r.get("coverage")]
    if not covs:
        return {"chapters": len(rows)}
    items = sum(c["items"] - len(c.get("unanswered") or []) for c in covs)
    realised = sum(c["realised"] for c in covs)
    return {"chapters": len(rows), "items": items, "realised": realised,
            "share": round(realised / items, 3) if items else None,
            "missing": sum(len(c.get("missing") or []) for c in covs),
            "contradicted": sum(len(c.get("contradicted") or []) for c in covs),
            "unanswered": sum(len(c.get("unanswered") or []) for c in covs)}


def evaluate_run(store: RunStore, language: str) -> dict:
    chapters = _chapters(store)
    story = "\n\n".join(d.text for d in chapters)
    spec = store.maybe("spec.json", Spec)
    plan = store.maybe("plan.json", Plan)
    det = detect_language(story) if story else None
    syn_style = stylometrics(story, language)
    words = word_count(story)
    target = spec.target_words if spec else words
    report: dict = {
        "language": {"expected": language, "detected": det.code if det else None,
                     "ok": bool(det and det.code == language),
                     "chapters_off_language": [d.index for d in chapters if d.language != language]},
        "length": {"words": words, "target": target, "ratio": round(words / target, 3) if target else None,
                   "chapters": len(chapters)},
        "stylometrics": syn_style,
    }
    if not store.exists("input/source.txt"):
        return report

    source = store.read_text("input/source.txt")
    src_ch = split_chapters(source)
    src_style = stylometrics(source, language)
    tmap = store.maybe("transform.json", TransformMap) or TransformMap()
    mapping = tmap.as_dict()
    bible = store.maybe("bible_source.json", Bible) or Bible()
    src_words = [float(c.words) for c in src_ch]
    syn_words = [float(d.word_count) for d in chapters]
    style_cmp = {k: {"source": src_style.get(k), "synthetic": syn_style.get(k),
                     "rel_diff": round(_rel(src_style.get(k, 0), syn_style.get(k, 0)), 3)}
                 for k in STYLE_KEYS if k in src_style}
    # Unit of comparison: chapters when both texts have the same three or more, else ten equal parts.
    if len(src_ch) >= 3 and len(src_ch) == len(chapters):
        units, unit_kind = ([c.text for c in src_ch], [d.text for d in chapters]), "chapters"
    else:
        units, unit_kind = (segments(source), segments(story)), "segments"
    layout_ok = layout_reliable(src_style)
    if not layout_ok and "mean_paragraph_words" in style_cmp:  # page/OCR breaks are not the author's paragraphs
        style_cmp["mean_paragraph_words"]["not_measured"] = True
    diffs = [v["rel_diff"] for v in style_cmp.values() if not v.get("not_measured")]
    syn_scenes = [len(c.scenes) for c in plan.chapters] if plan else []
    src_scenes = [len(c.scenes) for c in bible.chapters]
    report["fidelity"] = {
        "chapter_count": {"source": len(src_ch), "synthetic": len(chapters), "equal": len(src_ch) == len(chapters)},
        "chapter_length_pearson": (_round(pearson(src_words, syn_words))
                                   if len(src_words) == len(syn_words) and len(src_words) >= MIN_CHAPTERS_R else None),
        "total_length_ratio": round(words / max(sum(src_words), 1), 3),
        "scenes_per_chapter_match": (round(sum(a == b for a, b in zip(src_scenes, syn_scenes, strict=False)) / len(src_scenes), 3)
                                     if src_scenes and syn_scenes else None),
        "stylometric_mean_rel_diff": round(sum(diffs) / len(diffs), 3) if diffs else None,
        "stylometrics": style_cmp,
        "characters": character_fidelity(*units, bible, mapping, min_mentions=3 if len(source.split()) > 4000 else 2),
        "chapter_count_match": 1.0 if len(src_ch) == len(chapters) else 0.0,
        "comparison_unit": unit_kind,
    }
    report["fidelity"]["pacing_profile_r"], report["fidelity"]["pacing_note"] = pacing_profile(*units, language)
    report["variety"] = variety_report(source, story, store.maybe("variety.json", LanguageVariety),
                                       spec.variety if spec else None)
    originals = [k for k, v in mapping.items() if k != v] or [e.name for e in bible.entities]
    report["leakage"] = leakage_report(source, story, originals)

    # Names on both sides are excluded from style measures: replacing them is the point.
    names = name_tokens([*mapping.keys(), *mapping.values(), *(a for e in bible.entities for a in [e.name, *e.aliases])])
    exclude = names | proper_noun_tokens(source) | proper_noun_tokens(story)
    report["fidelity"]["function_word_cosine"] = _round(function_word_cosine(source, story, exclude))
    report["self_agreement"] = self_agreement(source, language, exclude)
    g_src = gender_shares(source, language, bible_characters(bible))
    g_syn = gender_shares(story, language, bible_characters(bible, mapping))
    report["fidelity"]["gender"] = {
        k: {"source": g_src.get(k), "synthetic": g_syn.get(k),
            "abs_diff": None if g_src.get(k) is None or g_syn.get(k) is None else round(abs(g_src[k] - g_syn[k]), 4)}
        for k in ("female_mention_share", "female_pronoun_share") if k in g_src}
    report["divergence"] = {"char3_jsd": _round(char_ngram_jsd(source, story, {n for n in [*mapping, *mapping.values()]}))}

    # The property catalogue: one number per property, computed the same way on T and S.
    # Corpus-level instruments (rank agreement, dispersion, distinguishability, replication)
    # read this block.
    sp, yp = style_profile(source, language), style_profile(story, language)
    feats = {k: {"source": sp.get(k), "synthetic": yp.get(k)} for k in sp}
    feats["chapters"] = {"source": float(len(src_ch)), "synthetic": float(len(chapters))}
    feats["mean_chapter_words"] = {"source": round(sum(src_words) / max(len(src_words), 1), 1),
                                   "synthetic": round(sum(syn_words) / max(len(syn_words), 1), 1)}
    if src_scenes and syn_scenes:
        feats["scenes_per_chapter"] = {"source": round(sum(src_scenes) / len(src_scenes), 3),
                                       "synthetic": round(sum(syn_scenes) / len(syn_scenes), 3)}
    for k, v in report["fidelity"]["gender"].items():
        if v["source"] is not None and v["synthetic"] is not None:
            feats[k] = {"source": v["source"], "synthetic": v["synthetic"]}
    report["features"] = feats
    main = [e for e in bible.characters() if e.mentions >= 3][:10]
    chars = [(e.name, [e.name, *e.aliases], [mapping[f] for f in [e.name, *e.aliases] if f in mapping and mapping[f] != f])
             for e in main]
    rec_path = store.root / "recovered" / "bible_source.json"
    if rec_path.exists() and bible.entities:  # KG: what the synthetic text realises of the design (and so of the source)
        from psalm_saga.eval.kg_align import text_comparison
        from psalm_saga.graph import build_graph, compare_graphs

        cmp = text_comparison(store, "design")
        if cmp is not None:
            report["structure_basis"] = "design"
            report["alignment"] = cmp.get("alignment_stats") or {}
        else:  # runs analysed before the design alignment existed
            cmp = compare_graphs(build_graph(bible), build_graph(Bible.model_validate_json(rec_path.read_text(encoding="utf-8"))),
                                 mapping)
            report["structure_basis"] = "source"
        report["structure"] = cmp["summary"]
        cal_path = store.root / "calibration" / "bible_source.json"
        ceiling = None
        if cal_path.exists():  # the extractor run twice on the source: its agreement with itself
            ceiling = compare_graphs(build_graph(bible), build_graph(Bible.model_validate_json(cal_path.read_text(encoding="utf-8"))),
                                     {})["summary"]
            report["structure_ceiling"] = ceiling
        report["kg"] = kg_scores(cmp["summary"], ceiling)
    report["coverage"] = coverage_report(store)
    report["distributions"] = distribution_report(source, story, [c.text for c in src_ch], [d.text for d in chapters],
                                                  chars, exclude)
    fs, fy = form_metrics(source), form_metrics(story)
    form = {"source": fs["form"], "synthetic": fy["form"], "match": 1.0 if fs["form"] == fy["form"] else 0.0}
    if fs["form"] == "verse":
        form.update(line_words={"source": fs["line_words_mean"], "synthetic": fy["line_words_mean"]},
                    line_words_rel_diff=round(_rel(fs["line_words_mean"], fy["line_words_mean"]), 3),
                    stanza={"source": fs["lines_per_stanza_mean"], "synthetic": fy["lines_per_stanza_mean"]},
                    stanza_rel_diff=round(_rel(fs["lines_per_stanza_mean"], fy["lines_per_stanza_mean"]), 3),
                    rhyme={"source": fs["rhyme_share"], "synthetic": fy["rhyme_share"]},
                    rhyme_share_diff=round(abs(fs["rhyme_share"] - fy["rhyme_share"]), 3))
    report["form"] = form
    report["not_measurable"] = missing_reasons(report, language)
    kind = store.read_json("text_kind.json") if store.exists("text_kind.json") else None
    if kind:
        report["text_kind"] = kind
        if not kind.get("has_cast", True):
            for k in NARRATIVE_KEYS:
                report["not_measurable"][k] = (f"not applicable: the source is {_kind_phrase(kind)}, without a cast of "
                                               "characters moving through scenes and events")
    if fs["form"] != "verse":
        for k in ("verse_lines", "verse_stanzas", "verse_rhyme"):
            report["not_measurable"][k] = "not applicable: the source is not verse"
    if not layout_ok:
        report["distributions"]["paragraph_length"].update(overlap=None, ks=None, ks_p=None)
        report["distributions"]["paragraph_length"]["note"] = "source paragraphing is page or OCR layout"
        report["not_measurable"]["paragraph_overlap"] = (
            "the source's paragraphs look like page or OCR breaks (few blocks of hundreds of words), so paragraph "
            "length is not a property of the text")
    return report
