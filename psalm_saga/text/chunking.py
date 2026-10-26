"""Split long sources into chapter-aligned chunks small enough for reliable extraction.

A 100k-word novel never goes into a single prompt: it is split on chapter headings
(multilingual), long chapters are split further on paragraph boundaries, and texts
without headings are cut into pseudo-chapters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_WORDS = (
    "chapter|hoofdstuk|kapitel|chapitre|capítulo|capitulo|capitolo|rozdział|kapittel|"
    "book|boek|buch|livre|part|deel|teil|partie|parte|del|canto|letter|brief|stave"
)
_ROMAN = r"[IVXLCDM]+"
_HEADING_RE = re.compile(
    rf"""^\s*(?:
        \#{{1,3}}\s+\S.{{0,100}}                                  # markdown heading
      | (?:{_HEADING_WORDS})\s+(?:\d+|{_ROMAN}|[^\W\d_]+)\b.{{0,80}}  # "Hoofdstuk 3: ..."
      | {_ROMAN}\.?(?:\s+.{{0,60}})?                               # "IV." or "IV. De storm"
      | \d{{1,3}}\.?(?:\s+[^\W\d_].{{0,60}})?                      # "12" or "12. De storm"
    )\s*$""",
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)


def word_count(text: str) -> int:
    return len(text.split())


@dataclass
class Chapter:
    index: int
    title: str
    text: str

    @property
    def words(self) -> int:
        return word_count(self.text)


@dataclass
class Chunk:
    index: int
    chapter: int
    chapter_title: str
    part: int  # part within the chapter
    text: str

    @property
    def words(self) -> int:
        return word_count(self.text)


def split_chapters(text: str, *, min_words: int = 40, pseudo_chapter_words: int = 5000) -> list[Chapter]:
    text = re.sub(r"\r+\n", "\n", text).replace("\r", "\n").strip()
    candidates = []
    for m in _HEADING_RE.finditer(text):
        line = m.group(0).strip()
        # A heading stands on its own line between blank lines (or at the start).
        before = text[max(0, m.start() - 2) : m.start()]
        if m.start() > 0 and "\n" not in before:
            continue
        candidates.append((m.start(), m.end(), line.lstrip("#").strip()))

    chapters: list[Chapter] = []
    if len(candidates) >= 2:
        pre = text[: candidates[0][0]].strip()
        bodies = []
        for i, (_s, e, title) in enumerate(candidates):
            end = candidates[i + 1][0] if i + 1 < len(candidates) else len(text)
            bodies.append((title, text[e:end].strip()))
        # Drop table-of-contents runs: headings with (almost) no body before the real text starts.
        merged: list[tuple[str, str]] = []
        for title, body in bodies:
            if word_count(body) < min_words and not merged:
                continue
            if word_count(body) < min_words and merged:
                t, b = merged[-1]
                merged[-1] = (t, f"{b}\n\n{title}\n\n{body}".strip())
                continue
            merged.append((title, body))
        if len(merged) >= 2:
            if word_count(pre) >= min_words * 5:
                merged.insert(0, ("", pre))
            chapters = [Chapter(i + 1, t, b) for i, (t, b) in enumerate(merged)]
    if not chapters:  # a collection of poems: each titled poem is a chapter
        from psalm_saga.text.form import form_profile, verse_sections

        if form_profile(text)["form"] == "verse":
            parts = verse_sections(text)
            if len(parts) >= 3:
                chapters = [Chapter(i + 1, t, b) for i, (t, b) in enumerate(parts)]
    if not chapters:
        chapters = _pseudo_chapters(text, pseudo_chapter_words)
    return chapters


def _paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1 and word_count(text) > 400:  # single-newline formatted text
        paras = [p.strip() for p in text.split("\n") if p.strip()]
    return paras


def _pack(paras: list[str], limit: int) -> list[str]:
    out, cur, n = [], [], 0
    for p in paras:
        w = word_count(p)
        if cur and n + w > limit:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out


def _pseudo_chapters(text: str, size: int) -> list[Chapter]:
    total = word_count(text)
    if total <= size * 1.3:
        return [Chapter(1, "", text)]
    return [Chapter(i + 1, "", body) for i, body in enumerate(_pack(_paragraphs(text), size))]


def chunk_chapters(chapters: list[Chapter], *, chunk_words: int = 4000) -> list[Chunk]:
    chunks: list[Chunk] = []
    for ch in chapters:
        pieces = [ch.text] if ch.words <= chunk_words * 1.25 else _pack(_paragraphs(ch.text), chunk_words)
        for part, body in enumerate(pieces):
            chunks.append(Chunk(len(chunks), ch.index, ch.title, part, body))
    return chunks
