"""extract: source text -> profile (deterministic) + story bible (map-reduce).

Scales to novel length: a 100k-word book becomes ~25-30 chunk calls that run in
parallel (bounded by the model's limiter), each well inside any context window,
and a single compact consolidation call. Nothing downstream ever sees the full text.
"""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, Field

from psalm_saga.artifacts import (
    Bible,
    ChapterInfo,
    ChapterSummary,
    ChunkNotes,
    Entity,
    EventNote,
    LanguageVariety,
    Relation,
    SceneNote,
    SourceProfile,
    TextKind,
)
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.text.chunking import chunk_chapters, split_chapters, word_count
from psalm_saga.text.language import detect_language, language_name
from psalm_saga.text.metrics import stylometrics
from psalm_saga.text.variety import variety_share, verify_markers

ROLE = "You are a meticulous literary analyst. You describe texts precisely, in your own words."


class _Group(BaseModel):
    ids: list[str]
    name: str
    kind: str = "character"
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    role: str = ""


class _Groups(BaseModel):
    groups: list[_Group]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def profile_source(text: str) -> SourceProfile:
    from psalm_saga.text.form import form_profile
    from psalm_saga.text.style import shape

    chapters = split_chapters(text)
    det = detect_language(text)
    return SourceProfile(
        language=det.code,
        language_confidence=round(det.confidence, 3),
        word_count=word_count(text),
        chapters=[ChapterInfo(index=c.index, title=c.title, word_count=c.words) for c in chapters],
        stylometrics=stylometrics(text, det.code),
        shape=shape(text),
        form=form_profile(text),
    )


def variety_excerpts(text: str, words: int = 450) -> str:
    """Beginning, middle, end and the most dialogue-dense stretch of the text."""
    toks = text.split()
    if len(toks) <= 4 * words:
        return text
    picks = [int(len(toks) * f) for f in (0.02, 0.5, 0.9)]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    quotes = "\"“”„«»'’"
    dense = max(range(len(paras)), key=lambda i: sum(paras[i].count(q) for q in quotes) / (len(paras[i]) + 50))
    dialogue = " ".join(" ".join(paras[dense : dense + 6]).split()[:words])
    return "\n...\n".join([*(" ".join(toks[p : p + words]) for p in picks), dialogue])


def count_mentions(text: str, names: list[str]) -> int:
    total = 0
    for n in {n for n in names if len(n) >= 2}:
        total += len(re.findall(rf"(?<![\w]){re.escape(n)}(?![\w])", text))
    return total


@register("extract")
class Extract(Stage):
    modes = ("source",)
    outputs = ("profile.json", "bible_source.json", "variety.json")

    async def classify(self, ctx: RunContext, text: str) -> None:
        """What kind of text this is (narrative, essay, …; narrator; whether it has a cast)."""
        ctx.store.write_json("text_kind.json", await ctx.json(
            self.model_role, ROLE, [Part(ctx.prompts.render("text_kind", excerpts=variety_excerpts(text)))], TextKind,
            temperature=self._temp(), hints=ctx.hints(), tag="extract:kind"))

    async def run(self, ctx: RunContext) -> None:
        text = ctx.store.read_text("input/source.txt")
        chapters = split_chapters(text, pseudo_chapter_words=int(self.params.get("pseudo_chapter_words", 5000)))
        if not ctx.store.exists("profile.json"):
            ctx.store.write_json("profile.json", profile_source(text))
        if not ctx.store.exists("variety.json"):
            ctx.store.write_json("variety.json", await self._variety(ctx, text))
        if not ctx.store.exists("text_kind.json") and self.params.get("classify", True):
            await self.classify(ctx, text)
        chunks = chunk_chapters(chapters, chunk_words=int(self.params.get("chunk_words", 4000)))
        ctx.emit("stage_progress", stage="extract", message=f"{len(chapters)} chapters, {len(chunks)} chunks")

        done = 0

        async def analyse(chunk):
            nonlocal done
            name = f"notes/chunk_{chunk.index:03d}.json"
            if ctx.store.exists(name):
                notes = ctx.store.read_json(name, ChunkNotes)
            else:
                prompt = ctx.prompts.render("extract_chunk", chunk=chunk, total=len(chunks), known="")
                notes = await ctx.json(self.model_role, ROLE, [Part(prompt)], ChunkNotes, temperature=self._temp(),
                                       hints=ctx.hints(), tag=f"extract:chunk{chunk.index}")
                ctx.store.write_json(name, notes)
            done += 1
            ctx.emit("stage_progress", stage="extract", done=done, total=len(chunks))
            return chunk, notes

        results = await gather_limited(chunks, analyse, int(self.params.get("parallel", 8)))
        bible = self._merge(results, chapters)
        if self.params.get("consolidate", True) and len(bible.entities) > 1:
            bible = await self._consolidate(ctx, bible)
        # Deterministic mention counts and chapter presence, from the text itself.
        by_chapter = {c.index: c.text for c in chapters}
        for e in bible.entities:
            names = [e.name, *e.aliases]
            e.chapters = [i for i, t in by_chapter.items() if count_mentions(t, names)] or e.chapters
            e.mentions = sum(count_mentions(t, names) for t in by_chapter.values())
        bible.entities.sort(key=lambda e: (-e.mentions, e.name))
        ctx.store.write_json("bible_source.json", bible)

    def _temp(self) -> float:
        """Analysis is measurement: run it cold, so that two analyses of the same text agree."""
        return float(self.params.get("temperature", 0.2))

    async def _variety(self, ctx: RunContext, text: str) -> LanguageVariety:
        """Detect the language variety and keep only marker forms the source really uses."""
        if not self.params.get("detect_variety", True):
            return LanguageVariety()
        prompt = ctx.prompts.render("variety", language=language_name(ctx.language), excerpts=variety_excerpts(text))
        v = await ctx.json(self.model_role, ROLE, [Part(prompt)], LanguageVariety, temperature=self._temp(),
                           hints=ctx.hints(markers=6, standard=True), tag="extract:variety")
        if v.standard:
            return LanguageVariety()
        v.markers = verify_markers(text, v.markers)
        m = variety_share(text, v)
        v.source_share = m["share"] if m else None
        ctx.emit("stage_progress", stage="extract",
                 message=f"language variety: {v.name} ({len(v.markers)} verified markers, share {v.source_share})")
        return v

    @staticmethod
    def _merge(results, chapters) -> Bible:
        ents: dict[str, Entity] = {}
        alias_of: dict[str, str] = {}
        chap_notes: dict[int, list[ChunkNotes]] = defaultdict(list)
        relations: list[tuple[str, str, str, str]] = []
        for chunk, notes in results:
            chap_notes[chunk.chapter].append(notes)
            for en in notes.entities:
                keys = [_norm(en.name), *(_norm(a) for a in en.aliases)]
                eid = next((alias_of[k] for k in keys if k in alias_of), None)
                if eid is None:
                    eid = f"e{len(ents) + 1}"
                    ents[eid] = Entity(id=eid, name=en.name.strip(), kind=en.kind, description=en.description, role=en.role)
                e = ents[eid]
                for a in [en.name, *en.aliases]:
                    if _norm(a) != _norm(e.name) and a.strip() and a.strip() not in e.aliases:
                        e.aliases.append(a.strip())
                    alias_of.setdefault(_norm(a), eid)
                if en.description and en.description not in e.description and len(e.description) < 900:
                    e.description = f"{e.description} {en.description}".strip()
                if en.role and not e.role:
                    e.role = en.role
                if e.gender == "unknown" and en.kind == "character" and en.gender != "unknown":
                    e.gender = en.gender
                if chunk.chapter not in e.chapters:
                    e.chapters.append(chunk.chapter)
            relations += [(r.source, r.target, r.type, r.description) for r in notes.relations]
        rels, seen = [], set()
        for s, t, typ, desc in relations:
            a, b = alias_of.get(_norm(s)), alias_of.get(_norm(t))
            if a and b and a != b and (a, b, typ.lower()) not in seen:
                seen.add((a, b, typ.lower()))
                rels.append(Relation(source=a, target=b, type=typ, description=desc))
        chap_summaries = []
        for ch in chapters:
            parts = chap_notes.get(ch.index, [])
            scenes: list[SceneNote] = [s for n in parts for s in n.scenes]
            events: list[EventNote] = []
            for n in parts:  # chunk-local cause indices become chapter-level ones
                offset = len(events)
                for i, e in enumerate(n.events):
                    ok = e.cause_index is not None and 0 <= e.cause_index < i
                    events.append(e.model_copy(update={"cause_index": e.cause_index + offset if ok else None}))
            chap_summaries.append(ChapterSummary(index=ch.index, title=ch.title, word_count=ch.words,
                                                 summary=" ".join(n.summary for n in parts),
                                                 scenes=scenes, events=events))
        style = [n.style for _, n in results if n.style]
        step = max(1, len(style) // 8)
        return Bible(entities=list(ents.values()), relations=rels, chapters=chap_summaries, style_notes=style[::step][:8])

    async def _consolidate(self, ctx: RunContext, bible: Bible) -> Bible:
        lines = [f"{e.id} | {e.kind} | {e.name} | aliases: {', '.join(e.aliases) or '-'} | {e.description[:240]}"
                 for e in bible.entities]
        groups = await ctx.json(self.model_role, ROLE, [Part(ctx.prompts.render("consolidate_entities", entities="\n".join(lines)))],
                                _Groups, temperature=self._temp(), hints=ctx.hints(groups=min(len(lines), 3)),
                                tag="extract:consolidate")
        by_id = {e.id: e for e in bible.entities}
        remap: dict[str, str] = {}
        merged: list[Entity] = []
        used: set[str] = set()
        for g in groups.groups:
            ids = [i for i in g.ids if i in by_id and i not in used]
            if not ids:
                continue
            used.update(ids)
            first = by_id[ids[0]]
            aliases = {a for i in ids for a in [by_id[i].name, *by_id[i].aliases]} | set(g.aliases)
            name = g.name.strip() or first.name
            aliases.discard(name)
            ent = Entity(id=first.id, name=name, kind=g.kind or first.kind, aliases=sorted(aliases),
                         description=g.description or first.description, role=g.role or first.role,
                         gender=next((by_id[i].gender for i in ids if by_id[i].gender != "unknown"), "unknown"),
                         chapters=sorted({c for i in ids for c in by_id[i].chapters}))
            merged.append(ent)
            for i in ids:
                remap[i] = first.id
        for e in bible.entities:  # anything the model dropped stays as-is
            if e.id not in used:
                merged.append(e)
                remap[e.id] = e.id
        rels, seen = [], set()
        for r in bible.relations:
            a, b = remap.get(r.source, r.source), remap.get(r.target, r.target)
            if a != b and (a, b, r.type.lower()) not in seen:
                seen.add((a, b, r.type.lower()))
                rels.append(Relation(source=a, target=b, type=r.type, description=r.description))
        return Bible(entities=merged, relations=rels, chapters=bible.chapters, style_notes=bible.style_notes)
