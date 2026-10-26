"""Text form: prose, verse or drama, measured deterministically and in any language.

The pipeline used to assume prose. A collection of rhymed poems then came back as choppy
prose, and the prose measures (sentences, paragraphs) were computed on lines. Form is a
property the synthetic text must keep, so it is measured on both texts with the same code:

  verse   line-based: words per line, lines per stanza, share of rhyming lines, dominant
          rhyme scheme, titles of separate poems
  drama   speaker labels (NAME. / NAME: at the start of a line) followed by speech
  prose   everything else (hard-wrapped prose, whose lines start in lower case and do not
          rhyme, stays prose)

Rhyme is approximated orthographically: two line-final words rhyme when their last vowel
group and everything after it agree (and the words differ). That works for the Latin-script
languages of the corpus without dictionaries; it misses eye-rhymes and sound-only rhymes.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
_VOWELS = "aeiouyàáâãäåèéêëìíîïòóôõöùúûüæœø"
_SPEAKER = re.compile(r"^\s*([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’ .-]{1,30})[.:]\s*(?:\S.*)?$")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def rhyme_key(line: str) -> str | None:
    ws = _WORD.findall(line)
    if not ws:
        return None
    w = _strip_accents(ws[-1].lower())
    m = re.search(rf"[{_VOWELS}]+[^{_VOWELS}]*$", w)
    if not m:
        return None
    key = m.group(0)
    return key


def _last_word(line: str) -> str:
    ws = _WORD.findall(line)
    return ws[-1].lower() if ws else ""


def stanzas(text: str) -> list[list[str]]:
    """Blocks separated by blank lines, as lists of non-empty lines."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip() and not ln.lstrip().startswith("#")]
        if lines:
            out.append(lines)
    return out


def _scheme(lines: list[str]) -> str:
    keys, labels, nxt = {}, [], 0
    for ln in lines:
        k = rhyme_key(ln)
        if k is None:
            labels.append("x")
            continue
        if k not in keys:
            keys[k] = "ABCDEFGHIJKLMNOP"[min(nxt, 15)]
            nxt += 1
        labels.append(keys[k])
    return "".join(labels)


def _rhyming(lines: list[str], window: int = 4) -> list[bool]:
    keys = [rhyme_key(ln) for ln in lines]
    words = [_last_word(ln) for ln in lines]
    out = []
    for i, k in enumerate(keys):
        hit = False
        if k:
            for j in range(max(0, i - window), min(len(lines), i + window + 1)):
                if j != i and keys[j] == k and words[j] != words[i]:
                    hit = True
                    break
        out.append(hit)
    return out


def _quantiles(v: list[float]) -> list[float]:
    if not v:
        return []
    s = sorted(v)
    return [round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1) for q in (0.1, 0.25, 0.5, 0.75, 0.9)]


def _is_title(block: list[str]) -> bool:
    if len(block) != 1:
        return False
    ln = block[0]
    ws = _WORD.findall(ln)
    return (0 < len(ws) <= 7 and ln[:1].isupper() and not re.search(r"[,;?!„“\"'«]", ln)
            and not ln.rstrip().endswith((",", ";", ":")))


def form_profile(text: str) -> dict:
    blocks = stanzas(text)
    lines = [ln for b in blocks for ln in b]
    n = len(lines)
    if n == 0:
        return {"form": "prose"}
    lw = [len(_WORD.findall(ln)) for ln in lines]
    med = statistics.median(lw)
    speaker = sum(bool(_SPEAKER.match(ln)) for ln in lines) / n
    cap_start = sum(ln[:1].isupper() or ln[:1] in "'‘„“\"«(" for ln in lines) / n
    no_end = sum(not ln.rstrip().endswith((".", "!", "?", "…", '"', "”", "’", "'", "»", ":")) for ln in lines) / n
    # Verse candidates: blocks of several short lines (titles excluded).
    body = [b for b in blocks if not _is_title(b)]
    multi = [b for b in body if len(b) >= 2]
    rhy = [r for b in multi for r in _rhyming(b)]
    rhyme_share = round(sum(rhy) / len(rhy), 3) if rhy else 0.0
    verse = (n >= 8 and med <= 10 and len(multi) >= 2 and (rhyme_share >= 0.3 or (cap_start >= 0.8 and no_end >= 0.25)))
    if speaker >= 0.12 and not verse:
        form = "drama"
    elif verse:
        form = "verse"
    else:
        form = "prose"
    out: dict = {"form": form, "lines": n, "line_words_median": med}
    if form == "verse":
        sizes = [len(b) for b in body]
        schemes = Counter()
        for b in multi:
            sch = _scheme(b)
            pairs = "AABB" if len(sch) >= 4 and sch[0] == sch[1] and sch[2] == sch[3] and sch[0] != sch[2] else \
                "ABAB" if len(sch) >= 4 and sch[0] == sch[2] and sch[1] == sch[3] and sch[0] != sch[1] else \
                "ABCB" if len(sch) >= 4 and sch[1] == sch[3] and sch[0] != sch[2] else \
                "ABBA" if len(sch) >= 4 and sch[0] == sch[3] and sch[1] == sch[2] and sch[0] != sch[1] else "other"
            schemes[pairs] += 1
        body_lw = [len(_WORD.findall(ln)) for b in body for ln in b]
        out.update({
            "line_words_mean": round(statistics.fmean(body_lw), 2) if body_lw else None,
            "line_words_quantiles": _quantiles(body_lw),
            "lines_per_stanza_mean": round(statistics.fmean(sizes), 2) if sizes else None,
            "lines_per_stanza_mode": Counter(sizes).most_common(1)[0][0] if sizes else None,
            "stanzas": len(body),
            "rhyme_share": rhyme_share,
            "rhyme_scheme": schemes.most_common(1)[0][0] if schemes else "none",
            "poem_titles": sum(_is_title(b) for b in blocks),
        })
    if form == "drama":
        out["speaker_line_share"] = round(speaker, 3)
    return out


def verse_sections(text: str) -> list[tuple[str, str]]:
    """Split a collection of poems into (title, body) at standalone title lines. Only used when
    the text is verse and at least three titles are found; otherwise the whole text is one part."""
    blocks = re.split(r"\n\s*\n", text.strip())
    parts: list[tuple[str, list[str]]] = []
    for b in blocks:
        lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
        if not lines:
            continue
        if _is_title(lines):
            parts.append((lines[0].rstrip("."), []))
        elif parts:
            parts[-1][1].append(b.strip())
        else:
            parts.append(("", [b.strip()]))
    titled = [p for p in parts if p[0] and p[1]]
    if len(titled) < 3:
        return [("", text.strip())]
    return [(t, "\n\n".join(bs)) for t, bs in parts if bs]


def form_brief(fp: dict) -> str:
    """Instructions for writing in the source's form (empty for prose)."""
    f = fp.get("form")
    if f == "verse":
        q = fp.get("line_words_quantiles") or []
        scheme = fp.get("rhyme_scheme", "none")
        scheme_txt = {"AABB": "in couplets (AABB)", "ABAB": "alternately (ABAB)", "ABCB": "on the second and fourth line (ABCB)",
                      "ABBA": "enclosed (ABBA)"}.get(scheme, "")
        lines = [
            "FORM: the source is VERSE. Write verse, not prose: one verse line per line of output, a blank line between "
            "stanzas, no paragraphs of running prose.",
            f"- Stanzas of {fp.get('lines_per_stanza_mode') or round(fp.get('lines_per_stanza_mean') or 4)} lines "
            f"(average {fp.get('lines_per_stanza_mean')}).",
            f"- Lines of about {fp.get('line_words_mean')} words" + (f" (most between {q[1]} and {q[3]})" if len(q) == 5 else "") + ".",
        ]
        rs = fp.get("rhyme_share") or 0
        if rs >= 0.3:
            lines.append(f"- Rhyme: {round(100 * rs)}% of the lines rhyme" + (f", {scheme_txt}" if scheme_txt else "")
                         + ". Rhyme as the source does; keep a regular beat.")
        else:
            lines.append("- The verse is largely unrhymed; keep the line breaks and the beat.")
        if (fp.get("poem_titles") or 0) >= 3:
            lines.append("- The source is a collection of separate poems, each with a short title on its own line; "
                         "write it the same way.")
        return "\n".join(lines)
    if f == "drama":
        return ("FORM: the source is DRAMA. Write it as a play: each speech starts with the speaker's name in capitals "
                "followed by a full stop, stage directions in brackets.")
    return ""


def verse_budget(fp: dict, target_words: int) -> str:
    """A word budget restated in the units a poet counts: lines and stanzas."""
    lw = fp.get("line_words_mean") or 6
    per = fp.get("lines_per_stanza_mode") or round(fp.get("lines_per_stanza_mean") or 4)
    lines = max(per, round(target_words / lw))
    stanzas = max(1, round(lines / per))
    return (f"- Length: about {target_words} words, that is about {stanzas} stanza{'s' if stanzas != 1 else ''} of "
            f"{per} lines ({stanzas * per} lines). Do not write more.")


def form_metrics(text: str) -> dict:
    """Flat numbers for comparison (same keys on source and synthetic)."""
    fp = form_profile(text)
    blocks = [b for b in stanzas(text) if not _is_title(b)]
    multi = [b for b in blocks if len(b) >= 2]
    rhy = [r for b in multi for r in _rhyming(b)]
    lw = [len(_WORD.findall(ln)) for b in blocks for ln in b]
    return {
        "form": fp["form"],
        "line_words_mean": round(statistics.fmean(lw), 2) if lw else 0.0,
        "lines_per_stanza_mean": round(statistics.fmean([len(b) for b in blocks]), 2) if blocks else 0.0,
        "rhyme_share": round(sum(rhy) / len(rhy), 3) if rhy else 0.0,
    }
