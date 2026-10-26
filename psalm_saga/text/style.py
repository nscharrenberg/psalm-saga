"""Measured style targets for the writer, and the gaps between a draft and those targets.

Language models write in a register of their own: shorter sentences, one-line paragraphs,
more dialogue and fewer commas than most literary prose, especially historical prose. A
description of the source's style in the specification ("long, layered sentences") is too weak
a signal to overcome that. Two things work better and stay inside the clean-room boundary,
because they pass on numbers, never wording:

  rhythm_brief  the shape of the source's rhythm (sentence- and paragraph-length quantiles,
                dialogue share, punctuation rates) stated as concrete targets in every
                drafting prompt;
  style_gaps    after drafting, the measured differences between a chapter and those targets,
                as concrete editing instructions for the conform stage.
"""

from __future__ import annotations

import statistics

from psalm_saga.text.metrics import has_speech, paragraphs, sentences, stylometrics, words

# Features the conform stage steers. Function-word profile, character n-grams and the full
# distributions are deliberately NOT steered, so they remain independent evidence of style.
TARGET_KEYS = ("mean_sentence_words", "sd_sentence_words", "mean_paragraph_words", "dialogue_word_share",
               "commas_per_1k", "question_sentence_share", "exclamation_sentence_share")


def layout_reliable(stylo: dict) -> bool:
    """Is the source's paragraphing authorial? Digitised texts often keep only page breaks: a few
    blocks of hundreds of words. Paragraph length is then not a property of the text and is
    neither targeted nor graded."""
    return (stylo.get("paragraphs") or 0) >= 4 and (stylo.get("mean_paragraph_words") or 0) <= 300


def target_keys(stylo: dict) -> tuple[str, ...]:
    keys = TARGET_KEYS if layout_reliable(stylo) else tuple(k for k in TARGET_KEYS if k != "mean_paragraph_words")
    if "dialogue_word_share" not in stylo:  # profiles written before this measure existed
        keys = tuple("dialogue_paragraph_share" if k == "dialogue_word_share" else k for k in keys)
    return keys


def _q(values: list[float], qs=(0.1, 0.25, 0.5, 0.75, 0.9)) -> list[float]:
    if not values:
        return []
    v = sorted(values)
    return [round(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))], 1) for q in qs]


def shape(text: str) -> dict:
    """Distribution shape of the rhythm: what a mean hides."""
    sl = [len(words(s)) for s in sentences(text)]
    paras = paragraphs(text)
    narr = [len(words(p)) for p in paras if not has_speech(p)]
    n = max(len(sl), 1)
    return {
        "sentence_quantiles": _q(sl),
        "paragraph_quantiles": _q([len(words(p)) for p in paras]),
        "narration_paragraph_median": round(statistics.median(narr), 1) if narr else None,
        "short_sentence_share": round(sum(x <= 6 for x in sl) / n, 3),
        "long_sentence_share": round(sum(x >= 30 for x in sl) / n, 3),
        # The rhythm itself, as numbers: per paragraph, the length of each sentence and whether it
        # contains direct speech. No words, so it can pass the clean-room boundary.
        "paragraph_rhythm": [{"s": [len(words(x)) for x in sentences(p)], "q": has_speech(p)} for p in paras][:1500],
    }


def distance(measured: dict, target: dict, keys: tuple[str, ...] | None = None) -> float:
    """Mean symmetric relative difference over the steered features (0 = on target)."""
    keys = keys or target_keys(target)
    diffs = []
    for k in keys:
        a, b = float(measured.get(k) or 0), float(target.get(k) or 0)
        if a == b:
            diffs.append(0.0)
            continue
        # Shares near zero: an absolute gap of 0.05 is negligible, not a 100% difference.
        if k.endswith("_share") and max(a, b) < 0.08:
            diffs.append(abs(a - b) / 0.08)
            continue
        diffs.append(abs(a - b) / max(abs(a), abs(b)))
    return round(sum(diffs) / len(diffs), 4) if diffs else 0.0


def _fmt(x: float | None, nd: int = 0) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def rhythm_brief(stylo: dict, shp: dict | None = None) -> str:
    """Concrete, numeric rhythm targets for the drafting prompt."""
    if not stylo:
        return ""
    shp = shp or {}
    lines = [f"- Sentences: average {_fmt(stylo.get('mean_sentence_words'), 1)} words "
             f"(spread {_fmt(stylo.get('sd_sentence_words'), 1)})."]
    sq = shp.get("sentence_quantiles")
    if sq and len(sq) == 5:
        lines.append(f"  A quarter of the sentences are shorter than {_fmt(sq[1])} words, half are longer than {_fmt(sq[2])}, "
                     f"and one in ten is longer than {_fmt(sq[4])} words.")
    if shp.get("short_sentence_share") is not None:
        lines.append(f"  Very short sentences (6 words or fewer) are {round(100 * shp['short_sentence_share'])}% of all sentences; "
                     f"long ones (30+ words) {round(100 * shp.get('long_sentence_share', 0))}%.")
    if layout_reliable(stylo):
        lines.append(f"- Paragraphs: average {_fmt(stylo.get('mean_paragraph_words'))} words"
                     + (f"; narration paragraphs typically {_fmt(shp.get('narration_paragraph_median'))} words"
                        if shp.get("narration_paragraph_median") else "") + ".")
        pq = shp.get("paragraph_quantiles")
        if pq and len(pq) == 5:
            lines.append(f"  Half the paragraphs are longer than {_fmt(pq[2])} words; a quarter longer than {_fmt(pq[3])}.")
    else:
        lines.append("- Paragraphs: the source's paragraphing was lost in digitisation; write full narrative paragraphs, "
                     "not one-line paragraphs.")
    dw = stylo.get("dialogue_word_share")
    dp = stylo.get("dialogue_paragraph_share", 0) or 0
    if (dw if dw is not None else dp) < 0.02:
        lines.append("- Dialogue: the source has practically no direct speech. Do not write dialogue; report what "
                     "people say in the narration.")
    else:
        share = f"about {round(100 * dw)}% of the words are direct speech" if dw is not None else \
            f"about {round(100 * dp)}% of paragraphs contain direct speech"
        lines.append(f"- Dialogue: {share}. Keep speech embedded in the narration as the source does; do not turn "
                     "scenes into exchanges of one-line replies, and do not add speech the source would narrate.")
    if stylo.get("mean_word_chars"):
        lines.append(f"- Words average {stylo['mean_word_chars']:.1f} letters: match the source's register of vocabulary "
                     "(plain or learned) rather than your own.")
    if stylo.get("first_person_per_1k") is not None:
        lines.append(f"- Personal pronouns per 1,000 words: first person (I, we) about {_fmt(stylo.get('first_person_per_1k'))}, "
                     f"third person (he, she, they) about {_fmt(stylo.get('third_person_per_1k'))}: keep the narrator as "
                     "present on the page as in the source.")
    lines.append(f"- Punctuation per 1,000 words: about {_fmt(stylo.get('commas_per_1k'))} commas, "
                 f"{_fmt(stylo.get('semicolons_per_1k'), 1)} semicolons, {_fmt(stylo.get('dashes_per_1k'), 1)} dashes. "
                 f"Questions are {round(100 * (stylo.get('question_sentence_share') or 0))}% and exclamations "
                 f"{round(100 * (stylo.get('exclamation_sentence_share') or 0))}% of sentences.")
    return ("These are measurements of the source's rhythm. Match them; they matter as much as the plot:\n"
            + "\n".join(lines))


def style_gaps(measured: dict, target: dict, shp_target: dict | None = None, tol: float = 0.15,
               shp_measured: dict | None = None) -> list[str]:
    """Concrete editing instructions for each steered feature that is off target."""
    out = []

    def off(k: str) -> bool:
        a, b = float(measured.get(k) or 0), float(target.get(k) or 0)
        if k.endswith("_share") and max(a, b) < 0.08:
            return abs(a - b) > 0.03
        return (abs(a - b) / max(abs(a), abs(b), 1e-9)) > tol

    m, t = measured, target
    if off("mean_sentence_words"):
        if (m.get("mean_sentence_words") or 0) < (t.get("mean_sentence_words") or 0):
            out.append(f"Sentences average {m['mean_sentence_words']:.1f} words; the target is {t['mean_sentence_words']:.1f}. "
                       "Join short sentences that belong together with commas, conjunctions and subordinate clauses, "
                       "and let descriptive sentences accumulate details.")
        else:
            out.append(f"Sentences average {m['mean_sentence_words']:.1f} words; the target is {t['mean_sentence_words']:.1f}. "
                       "Split the longest sentences at natural joints.")
    if off("sd_sentence_words"):
        sq = (shp_target or {}).get("sentence_quantiles") or []
        mq = (shp_measured or {}).get("sentence_quantiles") or []
        detail = ""
        if len(sq) == 5 and len(mq) == 5:
            detail = (f" In the source a quarter of the sentences are shorter than {sq[1]:.0f} words and one in ten is longer "
                      f"than {sq[4]:.0f}; here a quarter are shorter than {mq[1]:.0f} and one in ten longer than {mq[4]:.0f}.")
        if (m.get("sd_sentence_words") or 0) < (t.get("sd_sentence_words") or 0):
            out.append(f"Sentence lengths are too uniform (spread {m.get('sd_sentence_words', 0):.1f}; target "
                       f"{t['sd_sentence_words']:.1f}).{detail} Vary them as the source does: build some very long, "
                       "periodic sentences out of clauses and enumerations, and set some short ones against them.")
        else:
            out.append(f"Sentence lengths vary too much (spread {m.get('sd_sentence_words', 0):.1f}; target "
                       f"{t['sd_sentence_words']:.1f}).{detail} Even them out.")
    if layout_reliable(t) and off("mean_paragraph_words"):
        if (m.get("mean_paragraph_words") or 0) < (t.get("mean_paragraph_words") or 0):
            out.append(f"Paragraphs average {m['mean_paragraph_words']:.0f} words; the target is {t['mean_paragraph_words']:.0f}. "
                       "Merge consecutive narration paragraphs about the same moment, and keep a line of speech in the same "
                       "paragraph as the narration around it instead of on its own line.")
        else:
            out.append(f"Paragraphs average {m['mean_paragraph_words']:.0f} words; the target is {t['mean_paragraph_words']:.0f}. "
                       "Break long paragraphs where the focus or the moment changes.")
    dk = "dialogue_word_share" if "dialogue_word_share" in t else "dialogue_paragraph_share"
    if off(dk):
        a, b = m.get(dk) or 0, t.get(dk) or 0
        unit = "of the words are" if dk == "dialogue_word_share" else "of paragraphs contain"
        if b < 0.02:
            out.append(f"{round(100 * a)}% {unit} direct speech; the source has practically none. Turn direct speech "
                       "into reported speech in the narration.")
        elif a > b:
            out.append(f"{round(100 * a)}% {unit} direct speech; the target is {round(100 * b)}%. Report the less "
                       "important speech in the narration, but KEEP the key lines in direct speech (about "
                       f"{round(100 * b / a) if a else 0}% of the present speech): the source does use direct speech.")
        else:
            out.append(f"{round(100 * a)}% {unit} direct speech; the target is {round(100 * b)}%. Render some reported "
                       "speech as direct speech.")
    if off("commas_per_1k"):
        out.append(f"There are {m.get('commas_per_1k', 0):.0f} commas per 1,000 words; the target is {t.get('commas_per_1k', 0):.0f}. "
                   + ("Use more clauses and enumerations." if (m.get("commas_per_1k") or 0) < (t.get("commas_per_1k") or 0)
                      else "Simplify over-punctuated sentences."))
    if off("question_sentence_share"):
        out.append(f"{100 * (m.get('question_sentence_share') or 0):.0f}% of sentences are questions; the target is "
                   f"{100 * (t.get('question_sentence_share') or 0):.0f}%.")
    if off("exclamation_sentence_share"):
        out.append(f"{100 * (m.get('exclamation_sentence_share') or 0):.0f}% of sentences are exclamations; the target is "
                   f"{100 * (t.get('exclamation_sentence_share') or 0):.0f}%.")
    return out


VERSE_KEYS = ("line_words_mean", "lines_per_stanza_mean", "rhyme_share", "commas_per_1k", "exclamation_sentence_share")


def measure(text: str, lang: str, form: str = "prose") -> dict:
    m = dict(stylometrics(text, lang))
    if form == "verse":
        from psalm_saga.text.form import form_metrics

        fm = form_metrics(text)
        m.update({k: v for k, v in fm.items() if k != "form"}, form=fm["form"])
    return m


def verse_target(stylo: dict, fp: dict) -> dict:
    return {**stylo, "line_words_mean": fp.get("line_words_mean") or 0, "lines_per_stanza_mean": fp.get("lines_per_stanza_mean") or 0,
            "rhyme_share": fp.get("rhyme_share") or 0}


def verse_gaps(m: dict, t: dict, fp: dict, tol: float = 0.15) -> list[str]:
    out = []
    if m.get("form") != "verse":
        out.append("The passage is written as prose; the source is verse. Recast it as verse: short lines, one per "
                   "line of output, grouped in stanzas separated by blank lines.")

    def off(k):
        a, b = float(m.get(k) or 0), float(t.get(k) or 0)
        return abs(a - b) / max(abs(a), abs(b), 1e-9) > tol

    if off("line_words_mean"):
        out.append(f"Lines average {m.get('line_words_mean', 0):.1f} words; the target is {t['line_words_mean']:.1f}. "
                   + ("Break long lines." if (m.get("line_words_mean") or 0) > t["line_words_mean"] else "Join short lines."))
    if off("lines_per_stanza_mean"):
        out.append(f"Stanzas average {m.get('lines_per_stanza_mean', 0):.1f} lines; the target is "
                   f"{t['lines_per_stanza_mean']:.1f} (most often {fp.get('lines_per_stanza_mode')}).")
    if (t.get("rhyme_share") or 0) >= 0.3 and (m.get("rhyme_share") or 0) < (t.get("rhyme_share") or 0) - 0.1:
        scheme = fp.get("rhyme_scheme", "")
        out.append(f"{round(100 * (m.get('rhyme_share') or 0))}% of the lines rhyme; in the source "
                   f"{round(100 * t['rhyme_share'])}% do" + (f", in the scheme {scheme}" if scheme and scheme != "other" else "")
                   + ". Change line endings so that the lines rhyme as in the source, keeping what each line says.")
    return out


def rhythm_scaffold(shp: dict, target_words: int, position: float = 0.0, max_lines: int = 160) -> str:
    """A paragraph-by-paragraph rhythm plan for a passage of `target_words`, taken from the
    source's own sequence of paragraphs (numbers only) at the same relative position in the book,
    and scaled to the target length. Models follow a concrete scaffold far better than an average."""
    rows = [r for r in (shp or {}).get("paragraph_rhythm") or [] if r.get("s")]
    if len(rows) < 3 or target_words <= 0:
        return ""
    start = int(position * len(rows)) % len(rows)
    picked, total, i = [], 0, start
    while total < target_words and len(picked) < max_lines:
        r = rows[i % len(rows)]
        picked.append(r)
        total += sum(r["s"])
        i += 1
    scale = target_words / max(total, 1)
    lines = []
    for k, r in enumerate(picked, 1):
        sent = " · ".join(str(max(2, round(x * scale))) for x in r["s"])
        lines.append(f"P{k}: {sent}" + ("  [speech]" if r.get("q") else ""))
    return ("Rhythm scaffold, measured on the source at this point of the story (numbers only): one line per "
            "paragraph; each number is the length in words of one sentence; [speech] marks a paragraph with direct "
            "speech. Follow it closely: about this many paragraphs, sentences of about these lengths in this "
            "order, speech where it is marked. The content comes from the plan, the rhythm from the scaffold.\n"
            + "\n".join(lines))
