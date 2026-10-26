"""Deterministic text properties shared by the per-run and the corpus-level instruments.

Every function here is applied with the same code to the source T and the synthetic text S,
so a difference between the two values is a difference in the texts, not in the procedure.

  function_words      relative frequencies of the most frequent words, proper names excluded
                      (the input to Cosine Delta, F1b; Burrows 2002, Evert et al. 2017)
  char_ngram_jsd      Jensen-Shannon divergence of character trigram distributions (D4;
                      the divergence measure of Chim et al. 2025)
  gender_shares       share of character mentions that refer to women, and of gendered
                      pronouns that are feminine (F7; Underwood, Bamman & Lee 2018)
  property_vector     the catalogue of per-text properties used by R1-R5
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from psalm_saga.artifacts import Bible
from psalm_saga.text.language import STOPWORDS
from psalm_saga.text.metrics import mention_counts, stylometrics, words

# Gendered personal pronouns. Ambiguities are known and accepted (Dutch `zij`/`ze` and French
# `elle(s)` also cover plurals in some uses; `il` is also impersonal); the measure is read as a
# comparison between T and S, where the bias is the same on both sides. German `sie` is too
# ambiguous (she / they / formal you) to use.
GENDERED_PRONOUNS = {
    "en": {"female": {"she", "her", "hers", "herself"}, "male": {"he", "him", "his", "himself"}},
    "nl": {"female": {"zij", "haar", "haarzelf"}, "male": {"hij", "hem", "hemzelf"}},
    "fr": {"female": {"elle"}, "male": {"il", "lui"}},
}


def name_tokens(names: Iterable[str]) -> set[str]:
    """Capitalised word forms of names ("Juffrouw Pel" -> juffrouw, pel), never function words
    ("de" in "Dominee de Vries" stays in the vocabulary)."""
    stop = set().union(*STOPWORDS.values())
    out: set[str] = set()
    for n in names:
        out |= {w.lower() for w in words(n or "") if w[:1].isupper() and w.lower() not in stop}
    return out


def proper_noun_tokens(text: str, min_count: int = 2) -> set[str]:
    """Tokens that are capitalised in most of their occurrences (names, places)."""
    caps, total = Counter(), Counter()
    for w in words(text):
        lw = w.lower()
        total[lw] += 1
        if w[:1].isupper():
            caps[lw] += 1
    # Sentence-initial function words are capitalised too, but far less often than not.
    return {w for w, c in total.items() if c >= min_count and caps[w] / c > 0.6}


def word_freqs(text: str, exclude: set[str] = frozenset()) -> tuple[Counter, int]:
    toks = [w.lower() for w in words(text)]
    toks = [t for t in toks if t not in exclude]
    return Counter(toks), len(toks)


def function_words(texts: list[str], exclude: set[str], top: int = 300) -> list[str]:
    """The `top` most frequent words over `texts` (each text weighted equally), names excluded."""
    agg: Counter = Counter()
    for t in texts:
        c, n = word_freqs(t, exclude)
        for w, k in c.items():
            agg[w] += k / max(n, 1)
    return [w for w, _ in agg.most_common(top)]


def rel_freq_vector(text: str, vocab: list[str], exclude: set[str]) -> list[float]:
    c, n = word_freqs(text, exclude)
    return [c[w] / max(n, 1) for w in vocab]


def cosine(a: list[float], b: list[float]) -> float | None:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return None
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def function_word_cosine(source: str, synthetic: str, exclude: set[str], top: int = 200) -> float | None:
    """Single-pair stylistic proximity: cosine of MFW relative frequencies (no corpus z-scores).

    Cosine Delta proper (F1b) needs a corpus for the z-scores and is computed across items by
    the experiment runner; this is the per-run approximation that is always available."""
    vocab = function_words([source], exclude, top)
    return cosine(rel_freq_vector(source, vocab, exclude), rel_freq_vector(synthetic, vocab, exclude))


def _mask(text: str, names: set[str]) -> str:
    if not names:
        return text
    pat = re.compile(r"(?<![\w])(" + "|".join(sorted((re.escape(n) for n in names if len(n) > 1), key=len, reverse=True)) + r")(?![\w])",
                     re.IGNORECASE)
    return pat.sub("#", text)


def char_ngrams(text: str, n: int = 3) -> Counter:
    flat = re.sub(r"\s+", " ", text.lower())
    return Counter(flat[i : i + n] for i in range(len(flat) - n + 1))


def jsd(p: Counter, q: Counter) -> float | None:
    """Jensen-Shannon divergence in bits, in [0, 1]."""
    sp, sq = sum(p.values()), sum(q.values())
    if not sp or not sq:
        return None
    out = 0.0
    for k in p.keys() | q.keys():
        a, b = p.get(k, 0) / sp, q.get(k, 0) / sq
        m = (a + b) / 2
        if a:
            out += 0.5 * a * math.log2(a / m)
        if b:
            out += 0.5 * b * math.log2(b / m)
    return out


def char_ngram_jsd(source: str, synthetic: str, names: set[str], n: int = 3) -> float | None:
    """D4. Names are masked on both sides, so the replacement of names does not count."""
    return jsd(char_ngrams(_mask(source, names), n), char_ngrams(_mask(synthetic, names), n))


MIN_GENDER_MENTIONS = 10
MIN_GENDER_PRONOUNS = 20


def gender_shares(text: str, lang: str, characters: list[tuple[str, list[str]]]) -> dict:
    """Female share of (a) character mentions, using the bible's gender labels, (b) gendered pronouns.

    `characters` is a list of (gender, name forms) for the characters of this text."""
    fem = male = 0
    for gender, forms in characters:
        c = sum(mention_counts(text, [f]) for f in forms)
        if gender == "female":
            fem += c
        elif gender == "male":
            male += c
    # Shares of a handful of mentions swing wildly; below these counts they are not reported.
    out = {"female_mention_share": round(fem / (fem + male), 4) if fem + male >= MIN_GENDER_MENTIONS else None,
           "gendered_mentions": fem + male}
    pr = GENDERED_PRONOUNS.get(lang)
    if pr:
        c = Counter(w.lower() for w in words(text))
        f, m = sum(c[w] for w in pr["female"]), sum(c[w] for w in pr["male"])
        out["female_pronoun_share"] = round(f / (f + m), 4) if f + m >= MIN_GENDER_PRONOUNS else None
        out["gendered_pronouns"] = f + m
    return out


def bible_characters(bible: Bible, mapping: dict[str, str] | None = None, min_mentions: int = 1) -> list[tuple[str, list[str]]]:
    """(gender, name forms) per character; with `mapping`, the synthetic forms of the names."""
    out = []
    for e in bible.characters():
        if e.mentions < min_mentions and e.mentions:
            continue
        forms = [e.name, *e.aliases]
        if mapping is not None:
            forms = sorted({mapping.get(f, f) for f in forms})
        if forms:
            out.append((e.gender, forms))
    return out


# Properties that make up a text's profile for the corpus-level instruments (R1-R5). Each is a
# number computed the same way on T and S. Stylometric keys come from `stylometrics`.
PROFILE_STYLE_KEYS = (
    "mean_sentence_words", "sd_sentence_words", "mean_paragraph_words", "mean_word_chars", "mattr_500",
    "dialogue_paragraph_share", "question_sentence_share", "exclamation_sentence_share", "commas_per_1k",
    "semicolons_per_1k", "dashes_per_1k", "first_person_per_1k", "third_person_per_1k",
)


def style_profile(text: str, lang: str) -> dict[str, float]:
    st = stylometrics(text, lang)
    return {k: float(st[k]) for k in PROFILE_STYLE_KEYS if k in st}


# ------------------------------------------------------------------ distributions
#
# Means can agree while distributions differ (a text of only medium sentences and one that
# alternates very short and very long ones share a mean). These compare whole distributions,
# with two summary numbers that read the same way for every property:
#   overlap  histogram intersection: the share of the two distributions that coincides (1 = identical)
#   ks       Kolmogorov-Smirnov statistic: largest gap between the cumulative distributions (0 = identical)


def _hist(values: list[float], edges: list[float]) -> list[float]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        i = next((k for k in range(len(edges) - 1) if v < edges[k + 1]), len(edges) - 2)
        counts[max(i, 0)] += 1
    n = max(len(values), 1)
    return [round(c / n, 4) for c in counts]


def ks_statistic(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    a, b = sorted(a), sorted(b)
    i = j = 0
    d = 0.0
    while i < len(a) and j < len(b):
        x = min(a[i], b[j])
        while i < len(a) and a[i] <= x:
            i += 1
        while j < len(b) and b[j] <= x:
            j += 1
        d = max(d, abs(i / len(a) - j / len(b)))
    return round(d, 4)


def ks_pvalue(d: float, n: int, m: int) -> float | None:
    """Asymptotic two-sample Kolmogorov-Smirnov p-value (Stephens' correction)."""
    if not n or not m or d is None:
        return None
    en = math.sqrt(n * m / (n + m))
    lam = (en + 0.12 + 0.11 / en) * d
    if lam < 1e-3:
        return 1.0
    p = 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    return round(max(0.0, min(1.0, p)), 4)


def compare_distribution(src: list[float], syn: list[float], edges: list[float], unit: str) -> dict:
    hs, hy = _hist(src, edges), _hist(syn, edges)
    med = lambda v: sorted(v)[len(v) // 2] if v else None  # noqa: E731
    return {"edges": edges, "unit": unit, "source": hs, "synthetic": hy,
            "overlap": round(sum(min(a, b) for a, b in zip(hs, hy, strict=True)), 4) if src and syn else None,
            "ks": ks_statistic(src, syn), "n": [len(src), len(syn)],
            "ks_p": ks_pvalue(ks_statistic(src, syn), len(src), len(syn)),
            "median": [med(src), med(syn)], "mean": [round(sum(src) / len(src), 2) if src else None,
                                                   round(sum(syn) / len(syn), 2) if syn else None]}


def distribution_report(source: str, synthetic: str, src_chapters: list[str], syn_chapters: list[str],
                        characters: list[tuple[str, list[str], list[str]]], exclude: set[str]) -> dict:
    """Distributions of the same properties in T and S, for plotting and comparison.

    `characters`: (source name, source forms, synthetic forms) for the main characters."""
    from psalm_saga.text.metrics import has_speech, paragraphs, sentences

    def sl(t):
        return [float(len(words(s))) for s in sentences(t)]

    def pl(t):
        return [float(len(words(p))) for p in paragraphs(t)]

    def wl(t):
        return [float(len(w)) for w in words(t)]

    out = {
        "sentence_length": compare_distribution(sl(source), sl(synthetic), [0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 50, 65, 1e9], "words"),
        "paragraph_length": compare_distribution(pl(source), pl(synthetic), [0, 10, 20, 35, 50, 75, 100, 150, 200, 300, 1e9], "words"),
        "word_length": compare_distribution(wl(source), wl(synthetic), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 1e9], "letters"),
    }

    def share(chs: list[str]) -> list[float]:
        n = [len(words(c)) for c in chs]
        tot = sum(n) or 1
        return [round(x / tot, 4) for x in n]

    def dialogue(chs: list[str]) -> list[float]:
        out_ = []
        for c in chs:
            ps = paragraphs(c)
            out_.append(round(sum(1 for p in ps if has_speech(p)) / max(len(ps), 1), 3))
        return out_

    out["chapter_profile"] = {"length_share": {"source": share(src_chapters), "synthetic": share(syn_chapters)},
                              "dialogue_share": {"source": dialogue(src_chapters), "synthetic": dialogue(syn_chapters)}}
    rows = []
    for name, sforms, yforms in characters:
        a = sum(mention_counts(source, [f]) for f in sforms)
        b = sum(mention_counts(synthetic, [f]) for f in yforms) if yforms else 0
        rows.append((name, yforms[0] if yforms else "", a, b))
    ta, tb = sum(r[2] for r in rows) or 1, sum(r[3] for r in rows) or 1
    rows.sort(key=lambda r: -r[2])
    out["characters"] = [{"name": n, "synthetic_name": y, "source": round(a / ta, 4), "synthetic": round(b / tb, 4)}
                         for n, y, a, b in rows[:10]]
    vocab = function_words([source], exclude, 30)
    fs, fy = rel_freq_vector(source, vocab, exclude), rel_freq_vector(synthetic, vocab, exclude)
    out["function_words"] = [{"word": w, "source": round(1000 * a, 2), "synthetic": round(1000 * b, 2)}
                             for w, a, b in zip(vocab, fs, fy, strict=True)]
    return out
