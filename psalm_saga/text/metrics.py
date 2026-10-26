"""Deterministic measurements: stylometrics (data points to preserve) and verbatim
leakage (expression that must not survive). No model calls."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter

_SENT_SPLIT = re.compile(r"(?<=[.!?…])[\"'”’»)]*\s+(?=[\"'“„«(\-–—]*[A-ZÀ-ÖØ-Þ0-9])")
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_DIALOGUE_START = re.compile(r"^\s*[\"“„«‘'—–-]")

PRONOUNS = {
    "en": {"first": {"i", "me", "my", "mine", "myself", "we", "us", "our"}, "second": {"you", "your", "yours"},
           "third": {"he", "she", "him", "her", "his", "they", "them", "their", "hers"}},
    "nl": {"first": {"ik", "mij", "me", "mijn", "wij", "we", "ons", "onze"}, "second": {"jij", "je", "jou", "jouw", "u", "uw", "gij"},
           "third": {"hij", "zij", "ze", "hem", "haar", "zijn", "hen", "hun"}},
    "de": {"first": {"ich", "mich", "mir", "mein", "meine", "wir", "uns", "unser"}, "second": {"du", "dich", "dir", "dein", "ihr", "euch"},
           "third": {"er", "sie", "ihn", "ihm", "sein", "seine", "ihnen"}},
    "fr": {"first": {"je", "me", "moi", "mon", "ma", "mes", "nous", "notre"}, "second": {"tu", "te", "toi", "ton", "ta", "vous", "votre"},
           "third": {"il", "elle", "lui", "son", "sa", "ses", "ils", "elles", "leur"}},
}


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    return [s for s in _SENT_SPLIT.split(flat) if s.strip()]


_TERMINAL = tuple(".!?…:;\"”’»)'")


def _line_paragraphs(blocks: list[str]) -> bool:
    """Does this text mark paragraphs with single line breaks (one paragraph per line, blank lines
    only between sections)? True when blocks hold several lines that are long or end sentences;
    hard-wrapped prose (short lines that stop mid-sentence) keeps blank-line paragraphs."""
    multi = [b for b in blocks if b.count("\n") >= 1]
    if len(multi) < max(1, len(blocks) // 3):
        return False
    lines = [ln.strip() for b in multi for ln in b.split("\n") if ln.strip()]
    if len(lines) < 6:
        return False
    lens = sorted(len(_WORD.findall(ln)) for ln in lines)
    med = lens[len(lens) // 2]
    ends = sum(ln.rstrip().endswith(_TERMINAL) for ln in lines) / len(lines)
    return med >= 15 or (ends >= 0.6 and med >= 8)


def paragraphs(text: str) -> list[str]:
    """Paragraphs, whichever convention the text uses: blank lines between paragraphs, or one
    paragraph per line. A break inside a sentence (the previous block does not end a sentence and
    the next starts in lower case) is a page or OCR break, not a paragraph: the two are joined. The
    same rules apply to source and synthetic text."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if _line_paragraphs(blocks):
        blocks = [ln.strip() for b in blocks for ln in b.split("\n") if ln.strip()]
    out: list[str] = []
    for q in blocks:
        if q.lstrip().startswith("#"):
            continue
        if out and not out[-1].rstrip().endswith(_TERMINAL) and q[:1].islower():
            out[-1] = f"{out[-1].rstrip()} {q}"
        else:
            out.append(q)
    return out


# Direct speech: an opening quote mark after a line start, space or bracket, at least two words,
# then a closing mark ("t' huis" and "'t" are apostrophes, not speech).
_SPEECH = re.compile(r"(?:^|[\s(—–-])(?:„|“|«|‹|\"|‘|')(?=\S)([^\n„“”«»‹›\"‘’']{3,}?\s[^\n„“”«»‹›\"‘’']*?)(?:”|“|»|›|\"|’|')(?=[\s.,;:!?)—–-]|$)")
_DASH_SPEECH = re.compile(r"^\s*[—–]\s*\S")


def speech_spans(paragraph: str) -> list[str]:
    spans = [m.group(1) for m in _SPEECH.finditer(paragraph)]
    if not spans and _DASH_SPEECH.match(paragraph):  # dash-introduced dialogue (French, older Dutch)
        spans = [paragraph]
    return spans


def has_speech(paragraph: str) -> bool:
    return bool(speech_spans(paragraph))


def mattr(tokens: list[str], window: int = 500) -> float:
    """Moving-average type-token ratio: length-independent lexical richness."""
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    counts = Counter(tokens[:window])
    total = len(counts)
    acc = total
    for i in range(window, len(tokens)):
        out, inn = tokens[i - window], tokens[i]
        counts[out] -= 1
        if counts[out] == 0:
            del counts[out]
            total -= 1
        if counts[inn] == 0:
            total += 1
        counts[inn] += 1
        acc += total
    return acc / (len(tokens) - window + 1) / window


def stylometrics(text: str, lang: str = "en") -> dict[str, float]:
    toks = [w.lower() for w in words(text)]
    n = max(len(toks), 1)
    sents = sentences(text)
    slen = [len(words(s)) for s in sents] or [0]
    paras = paragraphs(text)
    plen = [len(words(p)) for p in paras] or [0]
    per_k = 1000 / n
    pr = PRONOUNS.get(lang)
    out = {
        "words": float(len(toks)),
        "sentences": float(len(sents)),
        "paragraphs": float(len(paras)),
        "mean_sentence_words": round(statistics.fmean(slen), 2),
        "sd_sentence_words": round(statistics.pstdev(slen), 2),
        "mean_paragraph_words": round(statistics.fmean(plen), 2),
        "mean_word_chars": round(statistics.fmean(len(t) for t in toks), 3) if toks else 0.0,
        "mattr_500": round(mattr(toks), 4),
        "dialogue_paragraph_share": round(sum(1 for p in paras if has_speech(p)) / max(len(paras), 1), 3),
        "dialogue_word_share": round(sum(len(words(sp)) for p in paras for sp in speech_spans(p)) / n, 3),
        "question_sentence_share": round(sum(s.rstrip("\"'”’» ").endswith("?") for s in sents) / max(len(sents), 1), 3),
        "exclamation_sentence_share": round(sum(s.rstrip("\"'”’» ").endswith("!") for s in sents) / max(len(sents), 1), 3),
        "commas_per_1k": round(text.count(",") * per_k, 2),
        "semicolons_per_1k": round(text.count(";") * per_k, 2),
        "colons_per_1k": round(text.count(":") * per_k, 2),
        "dashes_per_1k": round((text.count("—") + text.count("–")) * per_k, 2),
    }
    if pr:
        c = Counter(toks)
        for k, vocab in pr.items():
            out[f"{k}_person_per_1k"] = round(sum(c[w] for w in vocab) * per_k, 2)
    return out


def describe_stylometrics(m: dict[str, float]) -> str:
    """Human/LLM readable summary used as hard targets in the writing-style spec."""
    parts = [
        f"mean sentence length {m.get('mean_sentence_words', 0):.1f} words (sd {m.get('sd_sentence_words', 0):.1f})",
        f"mean paragraph length {m.get('mean_paragraph_words', 0):.0f} words",
        f"dialogue in {100 * m.get('dialogue_paragraph_share', 0):.0f}% of paragraphs",
        f"{100 * m.get('question_sentence_share', 0):.1f}% questions, {100 * m.get('exclamation_sentence_share', 0):.1f}% exclamations",
        f"commas {m.get('commas_per_1k', 0):.0f}/1k words, semicolons {m.get('semicolons_per_1k', 0):.1f}/1k, dashes {m.get('dashes_per_1k', 0):.1f}/1k",
        f"lexical richness MATTR {m.get('mattr_500', 0):.3f}",
    ]
    if "first_person_per_1k" in m:
        parts.append(f"pronouns per 1k words: 1st {m['first_person_per_1k']:.0f}, 2nd {m['second_person_per_1k']:.0f}, 3rd {m['third_person_per_1k']:.0f}")
    return "; ".join(parts) + "."


# ------------------------------------------------------------------ leakage


def _norm_tokens(text: str) -> list[str]:
    return [w.lower() for w in words(text)]


class SourceIndex:
    """Word n-gram index of a source text, built once and queried many times."""

    def __init__(self, source: str, n: int = 8):
        self.n = n
        self.src = _norm_tokens(source)
        self.index: dict[tuple, list[int]] = {}
        for i in range(len(self.src) - n + 1):
            self.index.setdefault(tuple(self.src[i : i + n]), []).append(i)

    def spans(self, target: str, *, min_len: int = 12, max_spans: int = 50) -> list[dict]:
        """Maximal word spans of `target` that also occur in the source (length >= min_len)."""
        n, src, tgt = self.n, self.src, _norm_tokens(target)
        if len(src) < n or len(tgt) < n:
            return []
        spans, i = [], 0
        while i <= len(tgt) - n:
            hits = self.index.get(tuple(tgt[i : i + n]))
            if not hits:
                i += 1
                continue
            best = 0
            for j in hits[:20]:
                k = n
                while i + k < len(tgt) and j + k < len(src) and tgt[i + k] == src[j + k]:
                    k += 1
                best = max(best, k)
            if best >= min_len:
                spans.append({"start": i, "length": best, "text": " ".join(tgt[i : i + best])})
            i += max(best - n + 1, 1)
        spans.sort(key=lambda s: -s["length"])
        return spans[:max_spans]


def verbatim_spans(source: str, target: str, *, n: int = 8, min_len: int = 12, max_spans: int = 50) -> list[dict]:
    return SourceIndex(source, n).spans(target, min_len=min_len, max_spans=max_spans)


def ngram_overlap(source: str, target: str, n: int = 8) -> float:
    """Share of target word n-grams that also occur in source."""
    src, tgt = _norm_tokens(source), _norm_tokens(target)
    if len(tgt) < n:
        return 0.0
    s = {tuple(src[i : i + n]) for i in range(len(src) - n + 1)}
    grams = [tuple(tgt[i : i + n]) for i in range(len(tgt) - n + 1)]
    return sum(g in s for g in grams) / len(grams)


def name_leakage(names: list[str], target: str) -> dict[str, int]:
    """Occurrences of original proper names in the target (word-boundary, case-sensitive)."""
    hits = {}
    for name in names:
        name = name.strip()
        if len(name) < 3 or not name[:1].isupper():
            continue
        c = len(re.findall(rf"(?<![\w]){re.escape(name)}(?![\w])", target))
        if c:
            hits[name] = c
    return hits


def leakage_report(source: str, target: str, names: list[str] | None = None) -> dict:
    spans = verbatim_spans(source, target)
    names = name_leakage(names or [], target)
    return {
        "ngram8_overlap": round(ngram_overlap(source, target, 8), 5),
        "ngram5_overlap": round(ngram_overlap(source, target, 5), 5),
        "longest_copied_span_words": spans[0]["length"] if spans else 0,
        "copied_spans_ge12": len(spans),
        "copied_spans": spans[:10],
        "names_leaked": len(names),
        "name_leakage": names,
    }


# ------------------------------------------------------------------ fidelity helpers


def pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (va * vb)


def spearman(a: list[float], b: list[float]) -> float | None:
    def ranks(x: list[float]) -> list[float]:
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    return pearson(ranks(a), ranks(b)) if len(a) == len(b) else None


def mention_counts(text: str, names: list[str]) -> int:
    return sum(len(re.findall(rf"(?<![\w]){re.escape(n)}(?![\w])", text)) for n in names if n)
