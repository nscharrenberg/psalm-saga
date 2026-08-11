"""Deterministic AI-writing-tell and cross-chapter repetition detection.

Pattern catalog ported from JuliusBrussee/skills' `deslopify` skill
(https://github.com/JuliusBrussee/skills/tree/main/skills/deslopify, `references/tells.md`): a
mechanical regex catalog of the statistical fingerprints of LLM-generated prose (puffery
vocabulary, negative parallelism, hedging/throat-clearing, rule-of-three, em-dash overuse) plus a
sentence-length-uniformity check. Deslopify's own core insight is why this lives in a tool rather
than a prompt instruction: a model cannot reliably self-detect its own statistical fingerprints,
because the same priors that generate a pattern also govern how the model judges it on review --
so detection here is mechanical (regex/arithmetic), and only the triage of what to do about a
finding (deslopify's Phase 2: fix the meaning, never paraphrase the pattern) is left to
deslop-agent's judgment. Mirrors `gate.py`'s PROCEED/BLOCKED pattern: a deterministic computation
the model reads and reasons from, not one it has to perform itself.

This module also detects a repetition class the upstream tells.md catalog doesn't cover: the same
descriptive phrase reused verbatim-ish across chapters. That's the actual root cause behind
session `20260811-104203-ab5081`'s bug report -- every chapter's writer-agent got the previous
chapter's full text and a running summary for *plot* continuity, but nothing checked whether the
new chapter's *prose* reused the previous chapter's scene-setting template and imagery, so
chapters 1 and 2 opened with near-identical "sun-soaked afternoon ... laughter echoed ... Quokkas'
eyes gleaming" passages.
"""

import re
from dataclasses import dataclass

from langchain_core.tools import tool

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CHAPTER_HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Finding:
    category: str
    snippet: str
    detail: str = ""


# --- 1. Negative parallelism -- the "not X but Y" family --------------------------------------

_NEGATIVE_PARALLELISM_PATTERNS = [
    re.compile(
        r"\bnot (just|only|merely|simply|solely)\b[^.;]{2,80}(but|it'?s| — )", re.IGNORECASE
    ),
    re.compile(r"\bisn'?t (just|only|merely|simply|about)\b", re.IGNORECASE),
    re.compile(r"\bit'?s not (a|an|the|that|about|just)\b[^.;]{2,80}(it'?s|but)", re.IGNORECASE),
    re.compile(
        r"\b(is|was|are|were)n'?t about\b[^.;]{2,60}\.\s*(it|this|that)'?s about", re.IGNORECASE
    ),
    re.compile(r"\bless about\b[^.;]{2,60}(than|and more about)", re.IGNORECASE),
    re.compile(r"\bmore than (just|a mere|simply)\b", re.IGNORECASE),
    re.compile(r"\bnot because\b[^.;]{2,80}\bbut because\b", re.IGNORECASE),
    re.compile(
        r"\bthe (question|point|issue|problem|goal|real \w+) "
        r"is(n'?t| not) (whether|about|just|if)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bno \w+, no \w+(, no \w+)?[,.]? just\b", re.IGNORECASE),
    re.compile(r"— not [^—.;]{2,60}, but ", re.IGNORECASE),
    re.compile(r"\bnot only\b[^.;]{2,80}\bbut (also )?", re.IGNORECASE),
    re.compile(r"\bwe'?re not (just )?(talking about|looking at|dealing with)\b", re.IGNORECASE),
    re.compile(r"\bgone are the days\b", re.IGNORECASE),
    re.compile(r"\bthis'?s the (thing|kicker|catch|twist)\b", re.IGNORECASE),
]

# --- 2. Puffery and inflated vocabulary ---------------------------------------------------------

_PUFFERY_WORDS = [
    "delve", "delving", "tapestry", "testament", "stands as", "seamless", "seamlessly",
    "pivotal", "paramount", "crucial", "underscores", "underscored", "landscape of", "realm of",
    "sphere of", "navigate the", "navigating the", "fosters", "fostering", "leverages",
    "leveraged", "meticulous", "meticulously", "intricate", "boasts", "game-changer",
    "game-changing", "gamechanging", "seismic shift", "monumental shift", "transformative shift",
    "seismic change", "monumental change", "transformative change", "unwavering", "commendable",
    "elevate the", "elevate your", "elevates the", "elevates your", "showcase", "showcases",
    "showcasing", "resonate", "resonates", "resonated", "compelling", "rich cultural heritage",
    "rich heritage", "rich tradition", "rich history", "vibrant", "plays a vital role",
    "plays a key role", "plays a crucial role", "plays a pivotal role", "deep dive", "deeper dive",
    "unlock the", "unlock your", "unlocks the", "unlocks your", "harness the", "harnesses the",
    "harnessing the", "embark on", "embarks on", "embarking on", "ever-evolving", "ever-changing",
    "fast-paced world", "fast-paced environment", "in today's", "at the end of the day",
    "when it comes to", "cutting-edge", "robust", "holistic", "synergy", "empower", "empowers",
    "empowering", "empowerment",
]
_PUFFERY_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _PUFFERY_WORDS) + r")\b", re.IGNORECASE
)

# --- 3. Hedging, both-sidesing, throat-clearing -------------------------------------------------

_HEDGING_PATTERNS = [
    re.compile(
        r"\bit'?s (worth|important) (to note|noting|to remember|to consider)\b", re.IGNORECASE
    ),
    re.compile(r"\bthat (being )?said,", re.IGNORECASE),
    re.compile(r"\bwhile (it'?s|this is) (true|important)\b", re.IGNORECASE),
    re.compile(r"\barguably\b", re.IGNORECASE),
    re.compile(r"\bin many ways\b", re.IGNORECASE),
    re.compile(r"\bto some (extent|degree)\b", re.IGNORECASE),
    re.compile(r"\bon the other hand\b", re.IGNORECASE),
    re.compile(r"\bat its core\b", re.IGNORECASE),
    re.compile(r"\bin essence\b", re.IGNORECASE),
    re.compile(r"\bessentially,", re.IGNORECASE),
    re.compile(r"\bultimately,", re.IGNORECASE),
    re.compile(r"\bin conclusion\b", re.IGNORECASE),
    re.compile(r"\bin summary\b", re.IGNORECASE),
    re.compile(r"\bto sum(marize| up)\b", re.IGNORECASE),
    re.compile(r"\boverall,", re.IGNORECASE),
    re.compile(r"\bin the end,", re.IGNORECASE),
    re.compile(r"\bneedless to say\b", re.IGNORECASE),
    re.compile(r"\bas (we|you) (can see|know|all know)\b", re.IGNORECASE),
    re.compile(r"\blet'?s (dive|unpack|explore|take a (look|closer look))\b", re.IGNORECASE),
    re.compile(r"\bwhether you('re| are)\b[^.;]{2,60}\bor\b", re.IGNORECASE),
]

# --- 4. Rule of three (false ranges are left to hand triage per tells.md) -----------------------

_RULE_OF_THREE_RE = re.compile(r"\b\w+, \w+, and \w+[.!?]")


def _find_puffery(text: str) -> list[Finding]:
    return [Finding("puffery", m.group(0), "") for m in _PUFFERY_RE.finditer(text)]


def _find_negative_parallelism(text: str) -> list[Finding]:
    findings = []
    for pattern in _NEGATIVE_PARALLELISM_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(Finding("negative_parallelism", m.group(0), ""))
    return findings


def _find_hedging(text: str) -> list[Finding]:
    findings = []
    for pattern in _HEDGING_PATTERNS:
        for m in pattern.finditer(text):
            findings.append(Finding("hedging", m.group(0), ""))
    return findings


def _find_rule_of_three(text: str) -> list[Finding]:
    return [Finding("rule_of_three", m.group(0), "") for m in _RULE_OF_THREE_RE.finditer(text)]


def _find_em_dash_density(text: str) -> list[Finding]:
    findings: list[Finding] = []
    words = _WORD_RE.findall(text)
    dash_count = text.count("—")
    if words and dash_count >= 2 and (dash_count / len(words)) * 150 > 1.0:
        findings.append(
            Finding(
                "em_dash_density",
                f"{dash_count} em dashes across {len(words)} words",
                "more than ~1 em dash per 150 words",
            )
        )
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if sentence.count("—") >= 2:
            findings.append(
                Finding("em_dash_density", sentence.strip()[:80], "two em dashes in one sentence")
            )
    return findings


def _find_uniform_sentence_length(text: str) -> list[Finding]:
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    lengths = [len(_WORD_RE.findall(s)) for s in sentences]

    findings: list[Finding] = []
    run_start = 0
    i = 1
    while i <= len(lengths):
        continues = i < len(lengths) and abs(lengths[i] - lengths[i - 1]) <= 4
        if continues:
            i += 1
            continue
        run_len = i - run_start
        if run_len >= 4:
            findings.append(
                Finding(
                    "uniform_sentence_length",
                    f"sentences {run_start + 1}-{i}",
                    f"{run_len} consecutive sentences within 4 words of each other "
                    f"(lengths {lengths[run_start:i]})",
                )
            )
        run_start = i
        i += 1
    return findings


# --- Cross-document / cross-chapter repetition ---------------------------------------------------


def find_repeated_phrases(a: str, b: str, min_words: int = 6) -> list[str]:
    """Word n-grams of at least `min_words` words that appear verbatim (case-insensitive) in both
    texts."""
    words_a = _WORD_RE.findall(a.lower())
    words_b = _WORD_RE.findall(b.lower())
    if len(words_a) < min_words or len(words_b) < min_words:
        return []

    ngrams_b = {tuple(words_b[i : i + min_words]) for i in range(len(words_b) - min_words + 1)}

    found: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for i in range(len(words_a) - min_words + 1):
        gram = tuple(words_a[i : i + min_words])
        if gram in ngrams_b and gram not in seen:
            seen.add(gram)
            found.append(" ".join(gram))
    return found


def _split_chapters(text: str) -> list[tuple[str, str]]:
    """Split an `assemble_draft`-style document into (heading, body) pairs on '## ' headings."""
    matches = list(_CHAPTER_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return []
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1).strip(), text[start:end].strip()))
    return sections


def find_cross_chapter_repetition(text: str, min_words: int = 6) -> list[Finding]:
    """Phrases of at least `min_words` words shared between two different '## '-headed sections."""
    sections = _split_chapters(text)
    findings: list[Finding] = []
    for i in range(len(sections)):
        title_a, body_a = sections[i]
        for title_b, body_b in sections[i + 1 :]:
            for phrase in find_repeated_phrases(body_a, body_b, min_words=min_words):
                findings.append(
                    Finding(
                        "cross_chapter_repetition",
                        phrase,
                        f"shared between {title_a!r} and {title_b!r}",
                    )
                )
    return findings


def scan_text(text: str, compare_against: str | None = None) -> list[Finding]:
    """Run every mechanical check against `text`.

    If `compare_against` is given (the previous chapter's full text, for a per-chapter scan),
    also flags phrases of 6+ words shared between the two. Otherwise, if `text` itself contains
    2+ '## '-headed sections (an assembled draft.md), checks for phrases shared between any two
    sections instead -- the whole-book pass has no single "previous chapter" to compare against.
    """
    findings: list[Finding] = []
    findings += _find_puffery(text)
    findings += _find_negative_parallelism(text)
    findings += _find_hedging(text)
    findings += _find_rule_of_three(text)
    findings += _find_em_dash_density(text)
    findings += _find_uniform_sentence_length(text)

    if compare_against:
        for phrase in find_repeated_phrases(text, compare_against):
            findings.append(
                Finding("repeated_phrase", phrase, "also appears in the compared text")
            )
    else:
        findings += find_cross_chapter_repetition(text)

    return findings


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "No AI-writing-tell or repetition findings."
    lines = [f"{len(findings)} finding(s):"]
    for f in findings:
        detail = f" -- {f.detail}" if f.detail else ""
        lines.append(f"- [{f.category}] {f.snippet!r}{detail}")
    return "\n".join(lines)


@tool
def scan_ai_tells(text: str, compare_against: str = "") -> str:
    """Mechanically scan prose for AI-writing tells and chapter-to-chapter repetition.

    Detects (by regex/arithmetic, not judgment): puffery vocabulary, negative-parallelism ("not
    X but Y") constructions, hedging/throat-clearing, rule-of-three padding, em-dash overuse, and
    runs of uniformly-lengthed sentences. Every finding is a candidate, not an automatic verdict --
    triage each one by its actual meaning before deciding to act on it; never "fix" a finding by
    paraphrasing the same pattern in different words.

    Args:
        text: The prose to scan -- one chapter's full text, or an entire assembled draft.md.
        compare_against: Optional. Another text (typically the immediately preceding chapter) to
            check `text` for reused 6+-word phrases against. Leave empty when scanning a whole
            assembled draft (multiple '## '-headed chapters) -- cross-chapter repetition is then
            checked between every pair of sections in `text` itself instead.
    """
    findings = scan_text(text, compare_against or None)
    return format_findings(findings)
