"""transform: source spec + bible -> synthetic spec + bible (clean-room boundary).

After this stage nothing downstream reads the source text: planning and drafting
see only the transformed spec and skeleton. That is the property the synthetic
corpus relies on, and it is what makes leakage measurable and attributable.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from psalm_saga.artifacts import (
    Bible,
    ChapterSummary,
    DimensionSpec,
    Entity,
    Relation,
    Rename,
    Spec,
    TransformMap,
)
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.text.language import language_name
from psalm_saga.text.variety import resolve as resolve_variety

ROLE = "You are a writer adapting a story's design into a new, independent story with the same structure."


class _EntityRewrite(BaseModel):
    id: str
    description: str
    role: str = ""


class _EntityRewrites(BaseModel):
    entities: list[_EntityRewrite]


class _OutlineChapter(BaseModel):
    index: int
    title: str = ""
    summary: str


class _NewOutline(BaseModel):
    chapters: list[_OutlineChapter]


class _Relations(BaseModel):
    relations: list[Relation] = Field(default_factory=list)


_CLOSE = 0.4  # content-word overlap above which a re-invented event or scene still tells the original's particulars


def _content(s: str) -> set[str]:
    from psalm_saga.graph import _tokens

    return _tokens(s)


def _pairs(old: ChapterSummary, new: ChapterSummary) -> list[tuple[str, str, str]]:
    out = [(f"scene {i + 1}", a.summary, b.summary) for i, (a, b) in enumerate(zip(old.scenes, new.scenes, strict=False))]
    out += [(f"event {i + 1}", a.description, b.description) for i, (a, b) in enumerate(zip(old.events, new.events, strict=False))]
    return out


def _overlap(a: str, b: str, names: set[str]) -> float:
    ta, tb = _content(a) - names, _content(b) - names
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _similarities(old: ChapterSummary, new: ChapterSummary, names: set[str]) -> list[float]:
    return [_overlap(a, b, names) for _, a, b in _pairs(old, new)]


def _too_close(old: ChapterSummary, new: ChapterSummary, names: set[str]) -> list[str]:
    """Items of a re-invented skeleton whose wording (names aside) still shares most content words with
    the original: the particulars were kept."""
    return [f"{k}: “{b[:160]}”" for k, a, b in _pairs(old, new) if _overlap(a, b, names) > _CLOSE]


class _Header(BaseModel):
    title: str
    logline: str


# ------------------------------------------------------------------ deterministic renaming


def _forms(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name.strip()) if t]


# Words that may start a description without making it a name ("de moeder", "het oude huis",
# "his sister"). Capitalised forms of these at the start of a phrase do not count as names.
_LEADING = {
    "de", "het", "een", "der", "des", "den", "zijn", "haar", "hun", "mijn", "uw", "onze", "ons", "zijne", "hare",
    "the", "a", "an", "his", "her", "their", "my", "your", "our", "its",
    "die", "das", "dem", "ein", "eine", "sein", "seine", "ihr", "ihre",
    "le", "la", "les", "l", "un", "une", "son", "sa", "ses",
}


def is_name_form(form: str) -> bool:
    """True for proper-name forms ("Adelheid", "Vrouw Holle", "de vrouw van ridder van Wallenstein"),
    false for descriptions ("de moeder", "het meisje", "weide", "het").

    Only names identify a work; descriptions are ordinary words. Renaming them corrupts the text
    ("hare moeder" -> "hare de vrouw van ridder van Bredeveld", "het" -> "de") and changes content
    the policy may have promised to keep (an apple tree is still an apple tree)."""
    toks = [t.strip(".,;:!?'’\"()") for t in _forms(form)]
    toks = [t for t in toks if t]
    if not toks or len(form.strip()) < 3:
        return False
    while len(toks) > 1 and toks[0].lower() in _LEADING:  # "de vrouw van ..." -> "vrouw van ..."
        toks = toks[1:]
    if len(toks) == 1:
        t = toks[0]
        return t[:1].isupper() and t.lower() not in _TITLES and t.lower() not in _LEADING
    # A phrase is a name if a word after its first is capitalised ("Vrouw Holle", "Graaf van Rotsburg");
    # a capitalised first word alone is just the start of a description ("Veld met hoog gras").
    return any(t[:1].isupper() for t in toks[1:])


_TITLES = {"vrouw", "heer", "mevrouw", "juffrouw", "meester", "graaf", "ridder", "oom", "tante", "moeder", "vader",
           "mr", "mrs", "miss", "sir", "lady", "lord", "frau", "herr", "madame", "monsieur", "grootmoeder", "grootvader"}


def name_renames(tmap: TransformMap, keep_real: bool = False) -> TransformMap:
    """Keep only renames of proper-name forms that actually change something. With `keep_real`,
    names of the real, shared world (marked `real` by the model) stay as they are."""
    kept = list(tmap.kept)
    keep = []
    for r in tmap.renames:
        if keep_real and r.real:
            if r.original not in kept:
                kept.append(r.original)
            continue
        if r.original != r.new and is_name_form(r.original):
            keep.append(r)
    return TransformMap(renames=keep, setting_shift=tmap.setting_shift, notes=tmap.notes, kept=kept)


def keeps_real_names(policy) -> bool:
    if policy.keep_real_names is not None:
        return bool(policy.keep_real_names)
    return policy.policy.get("world_building", "abstract") == "preserve"


def complete_renames(tmap: TransformMap, entities: list[Entity], keep_real: bool = False) -> TransformMap:
    """Make sure every name form (aliases, first/last name alone) has a replacement.

    Only proper-name forms are renamed (`is_name_form`); descriptive aliases such as "the mother"
    or "the girl" stay as they are, since they are not names and may refer to others."""
    tmap = name_renames(tmap, keep_real)
    mapping = tmap.as_dict()
    lower = {k.lower(): v for k, v in mapping.items()}
    out = list(tmap.renames)
    for e in entities:
        new_full = mapping.get(e.name) or lower.get(e.name.lower())
        if not new_full:
            continue
        old_tokens, new_tokens = _forms(e.name), _forms(new_full)
        own = {t.lower().rstrip("s") for t in _forms(e.name) if t[:1].isupper()}
        # An alias whose names all belong to other entities ("Adelheid's mother") is a description:
        # the names in it are renamed by their own entries, so the phrase reads naturally.
        candidates = [a for a in e.aliases if is_name_form(a)
                      and (own & {t.strip(".,'’").lower().rstrip("s") for t in _forms(a)[1:] + _forms(a)[:1] if t[:1].isupper()})]
        # Token-wise forms of personal names: "Deborah Jenkyns" -> "Deborah", "Jenkyns". Not for
        # places and things: "Flying Dutchman" -> "The Wraith" must not turn every "Flying" into "The".
        if len(old_tokens) > 1 and e.kind == "character":
            candidates += [old_tokens[0], old_tokens[-1]]
        for form in candidates:
            if not form or form in mapping or form.lower() in lower or len(form) < 3 or not is_name_form(form):
                continue
            if form in old_tokens and len(new_tokens) >= 1:
                idx = old_tokens.index(form)
                rep = new_tokens[min(idx, len(new_tokens) - 1)] if idx < len(old_tokens) - 1 else new_tokens[-1]
            else:
                # Alias like "Miss Jenkyns": swap the tokens we know.
                rep = form
                for i, tok in enumerate(old_tokens):
                    target = new_tokens[min(i, len(new_tokens) - 1)] if i < len(old_tokens) - 1 else new_tokens[-1]
                    rep = re.sub(rf"(?<!\w){re.escape(tok)}(?!\w)", target, rep)
                if rep == form:
                    rep = new_full
            if rep == form or rep.lower() in _LEADING or len(rep) < 2:
                continue
            mapping[form] = rep
            lower[form.lower()] = rep
            out.append(Rename(original=form, new=rep, kind=e.kind, note=f"form of {e.name}"))
    return TransformMap(renames=_drop_composites(out), setting_shift=tmap.setting_shift, notes=tmap.notes, kept=tmap.kept)


def _drop_composites(renames: list[Rename]) -> list[Rename]:
    """Make phrase renames agree with the single-name renames they contain.

    Once "Holle" -> "Ratelveer" exists, "het huis van Vrouw Holle" becomes "het huis van Vrouw
    Ratelveer" rather than whatever the model proposed for the whole phrase (it once proposed
    "het Berkenhuis van Vrouw Holle", which left the original name in place). The phrase keeps
    its entry, so lookups by full name (graph counterparts, character metrics) still work."""
    singles = {r.original: r.new for r in renames if len(_forms(r.original)) == 1}
    low = {k.lower(): v for k, v in singles.items()}
    out = []
    for r in renames:
        toks = [t.strip(".,;:'’\"()") for t in _forms(r.original)]
        caps = [t for i, t in enumerate(toks) if t[:1].isupper() and not (i == 0 and t.lower() in _LEADING)]
        names = [t for t in caps if t.lower() not in _TITLES]
        if len(toks) > 1 and names and all(t.lower() in low or t.lower().rstrip("s") in low for t in names):
            new = r.original
            for k, v in sorted(singles.items(), key=lambda kv: -len(kv[0])):
                new = re.sub(rf"(?<!\w){re.escape(k)}(?=(?:s|'s|’s)?(?!\w))", v, new)
            if r.original[:1].isupper() and r.new[:1].islower():
                new = new[:1].lower() + new[1:]
            r = r.model_copy(update={"new": new})
        out.append(r)
    return out


def apply_renames(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    keys = sorted((k for k in mapping if k and k != mapping[k] and is_name_form(k)), key=len, reverse=True)
    if not keys:
        return text
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(k) for k in keys) + r")(?=(?:s|'s|’s)?(?![\w]))")
    return pattern.sub(lambda m: mapping[m.group(1)], text)


def rename_model(obj: BaseModel, mapping: dict[str, str]) -> BaseModel:
    def walk(v):
        if isinstance(v, str):
            return apply_renames(v, mapping)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    return type(obj).model_validate(walk(obj.model_dump()))


def scene_shape(s, chapter_words: int = 0) -> str:
    """How much room a scene takes and how it is told, from the source's measurements (numbers only)."""
    bits = []
    if s.words and chapter_words:
        bits.append(f"{round(100 * s.words / max(chapter_words, 1))}% of the chapter")
    if s.dialogue is not None and s.words:
        bits.append("no direct speech" if s.dialogue < 0.01 else f"direct speech ≈ {round(100 * s.dialogue)}% of its words")
    if s.sentence_words:
        bits.append(f"sentences ≈ {s.sentence_words:.0f} words")
    if s.mode:
        bits.append(f"told mainly as {s.mode}")
    return "; ".join(bits)


def render_skeleton(ch: ChapterSummary) -> str:
    lines = [f"Chapter {ch.index}{(': ' + ch.title) if ch.title else ''} — {ch.word_count} words", f"Summary: {ch.summary}"]
    measured = sum(s.words for s in ch.scenes) or ch.word_count
    for i, s in enumerate(ch.scenes, 1):
        who = ", ".join(s.characters)
        shp = scene_shape(s, measured)
        if not (s.summary or who or s.setting):  # a design without its graph: only the measured shape
            lines.append(f"Scene {i}" + (f": {shp}" if shp else ""))
            continue
        lines.append(f"Scene {i}: {s.summary} | setting: {s.setting} | characters: {who} | purpose: {s.purpose} | pov: {s.pov}"
                     + (f" | shape: {shp}" if shp else ""))
    for e in ch.events:
        cause = f" (because: {e.caused_by})" if e.caused_by else ""
        lines.append(f"Event: {e.description}{cause}")
    return "\n".join(lines)


@register("transform")
class Transform(Stage):
    modes = ("source",)
    outputs = ("transform.json", "spec.json", "bible.json")  # + transform_log.json (how the skeleton was transformed)

    async def run(self, ctx: RunContext) -> None:
        # `variant` (set by an evaluation-guided fix) makes every call a fresh sample instead of a cache hit
        if self.params.get("variant"):
            ctx.state["variant"] = f"transform-{self.params['variant']}"
        try:
            await self._run(ctx)
        finally:
            ctx.state.pop("variant", None)

    async def _run(self, ctx: RunContext) -> None:
        policy = ctx.config.transform
        src_spec = ctx.store.read_json("spec_source.json", Spec)
        src_bible = ctx.store.read_json("bible_source.json", Bible)

        # 1. Names (an existing transform.json — e.g. hand-edited — is reused).
        keep_real = keeps_real_names(policy)
        if ctx.store.exists("transform.json"):
            tmap = complete_renames(ctx.store.read_json("transform.json", TransformMap), src_bible.entities, keep_real)
        elif policy.rename_entities and src_bible.entities:
            listing = "\n".join(
                f"- {e.name} [{e.kind}{', ' + e.role if e.role else ''}{', ' + e.gender if e.gender != 'unknown' else ''}] aliases: {', '.join(e.aliases) or '-'} — {e.description[:200]}"
                for e in src_bible.entities[: int(self.params.get("max_entities", 120))]
            )
            prompt = ctx.prompts.render(
                "transform_names", entities=listing, keep_culture=policy.keep_cultural_setting,
                language=language_name(ctx.language), setting_policy=policy.policy.get("world_building", "abstract"),
                notes=policy.notes, keep_real=keep_real,
            )
            tmap = await ctx.json(self.model_role, ROLE, [Part(prompt)], TransformMap,
                                  hints=ctx.hints(renames=min(len(src_bible.entities), 6)), tag="transform:names")
            tmap = complete_renames(tmap, src_bible.entities, keep_real)
            # Guarantee coverage: an entity the model skipped is flagged (kept), never silently leaked.
            missing = [e.name for e in src_bible.entities if is_name_form(e.name) and e.name not in tmap.as_dict()
                       and e.name not in tmap.kept]
            if tmap.kept:
                ctx.emit("stage_progress", stage="transform",
                         message=f"kept {len(tmap.kept)} real-world names: {', '.join(tmap.kept[:8])}")
            if missing:
                ctx.emit("warning", stage="transform", message=f"{len(missing)} entities without a new name", names=missing[:20])
        else:
            tmap = TransformMap()
        mapping = tmap.as_dict()
        ctx.store.write_json("transform.json", tmap)

        # 2. Spec, per dimension.
        renamed_spec: Spec = rename_model(src_spec, mapping)  # type: ignore[assignment]
        kept = [d for d in renamed_spec.dimensions if policy.policy.get(d.dimension, "preserve") == "preserve"]
        for d in kept:
            d.policy = "preserve"
            for item in d.items:
                item.evidence = ""
        kept_ctx = Spec(language=ctx.language, target_words=src_spec.target_words, chapters=src_spec.chapters,
                        dimensions=kept).render()
        renames_txt = "; ".join(f"{k} → {v}" for k, v in mapping.items()) or "(none)"

        async def transform_dim(d: DimensionSpec) -> DimensionSpec:
            pol = policy.policy.get(d.dimension, "preserve")
            if pol == "preserve":
                return d
            dim = ctx.taxonomy.get(d.dimension)
            prompt = ctx.prompts.render(
                "transform_dimension", dim=dim, policy=pol, renames=renames_txt, setting_shift=tmap.setting_shift,
                surface=", ".join(s.key for s in dim.subdimensions if s.surface) or "none",
                context=kept_ctx, original=Spec(language=ctx.language, target_words=0, chapters=0, dimensions=[d]).render(),
                subdims="\n".join(f"- {s_.key} ({s_.label}): {s_.guidance}" for s_ in dim.subdimensions),
            )
            out = await ctx.json(self.model_role, ROLE, [Part(prompt)], DimensionSpec,
                                 hints=ctx.hints(items=len(d.items)), tag=f"transform:{d.dimension}")
            out.dimension, out.policy = d.dimension, pol
            if len(out.items) != len(d.items):  # keep taxonomy shape
                by_key = {i.key: i for i in out.items}
                out.items = [by_key.get(i.key, i) for i in d.items]
            return out

        new_dims = await gather_limited(renamed_spec.dimensions, transform_dim, 6)
        hdr = await ctx.json(self.model_role, ROLE, [Part(Spec(language=ctx.language, target_words=0, chapters=0, dimensions=new_dims).render()),
                                                   Part("Give this synthetic story a new title (not the source's) and a one-sentence logline, in the output language.")],
                             _Header, hints=ctx.hints(), tag="transform:header")
        variety = resolve_variety(ctx.config.language.variety, renamed_spec.variety,
                                  policy.policy.get("writing_style", "preserve"))
        spec = Spec(language=ctx.language, title=hdr.title, logline=hdr.logline, target_words=src_spec.target_words,
                    chapters=src_spec.chapters, dimensions=new_dims, variety=variety,
                    notes="Synthetic counterpart. Policies: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in policy.policy.items())
                    + (f". Setting shift: {tmap.setting_shift}" if tmap.setting_shift else "."))
        ctx.store.write_json("spec.json", spec)

        # 3. Bible: entities, relations and chapter skeletons.
        bible: Bible = rename_model(src_bible, mapping)  # type: ignore[assignment]
        bible.style_notes = []  # source-derived wording; the spec carries style now
        pol = {k: policy.policy.get(k, "preserve") for k in ("character", "world_building", "plot_structure", "scene_sequence")}
        spec_people = spec.render(only=["character", "world_building"])
        if bible.entities and (pol["character"] != "preserve" or pol["world_building"] != "preserve"):
            await self._rewrite_entities(ctx, bible, pol["character"], pol["world_building"], spec_people)
        if bible.entities and "regenerate" in (pol["character"], pol["world_building"]):
            await self._regenerate_relations(ctx, bible, pol["character"], pol["world_building"], spec_people)
        log: dict = {"skeleton": "renamed"}
        if "regenerate" in (pol["plot_structure"], pol["scene_sequence"]):
            # The story itself is replaced: a new skeleton from the transformed specification and cast,
            # with the source's chapter count and lengths only.
            bible.chapters = await self._new_story(ctx, bible, spec)
            log["skeleton"] = "new story"
        elif any(v != "preserve" for v in pol.values()):
            spec_ex = spec.render(only=["plot_structure", "scene_sequence", "world_building", "character"])
            changed = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in pol.items() if v != "preserve")
            # Event and scene particulars must change when the plot or the scene sequence is re-invented;
            # with only characters or world re-invented, the events stay and their actors and settings change.
            check = "abstract" in (pol["plot_structure"], pol["scene_sequence"])
            names = {t for e in bible.entities for n in [e.name, *e.aliases] for t in _content(n)}
            sims: list[float] = []

            async def reskin(ch: ChapterSummary) -> ChapterSummary:
                too_close = ""
                out = ch
                for attempt in range(1 + int(self.params.get("reskin_retries", 1) if check else 0)):
                    prompt = ctx.prompts.render("transform_skeleton", renames=renames_txt, setting_shift=tmap.setting_shift,
                                                spec=spec_ex, chapter=ch, skeleton=render_skeleton(ch), policies=changed,
                                                too_close=too_close)
                    cand = await ctx.json(self.model_role, ROLE, [Part(prompt)], ChapterSummary,
                                          hints=ctx.hints(scenes=len(ch.scenes), events=len(ch.events), index=ch.index,
                                                          variant=f"{ctx.state.get('variant', '')}:{attempt}"),
                                          tag=f"transform:skeleton{ch.index}" + (f":r{attempt}" if attempt else ""))
                    if len(cand.scenes) != len(ch.scenes):
                        ctx.emit("warning", stage="transform",
                                 message=f"chapter {ch.index}: re-invention changed the scene count; trying again")
                        continue
                    out = cand
                    if not check:
                        break
                    close = _too_close(ch, cand, names)
                    if not close:
                        break
                    too_close = "\n".join(f"- {x}" for x in close)
                if out is ch:
                    ctx.emit("warning", stage="transform", message=f"chapter {ch.index}: kept the renamed skeleton")
                    return ch
                out.index, out.word_count = ch.index, ch.word_count
                for new, old in zip(out.scenes, ch.scenes, strict=True):  # measurements are the source's, not the model's
                    new.words, new.dialogue, new.sentence_words, new.mode = old.words, old.dialogue, old.sentence_words, old.mode
                    new.opening = ""
                sims.extend(_similarities(ch, out, names))
                return out

            bible.chapters = await gather_limited(bible.chapters, reskin, int(self.params.get("parallel", 8)))
            log["skeleton"] = "re-invented" if check else "re-cast"
            if sims:
                log["particular_overlap"] = {"mean": round(sum(sims) / len(sims), 3), "max": round(max(sims), 3),
                                             "above_threshold": sum(x > _CLOSE for x in sims), "items": len(sims)}
        ctx.store.write_json("bible.json", bible)
        ctx.store.write_json("transform_log.json", log)

    def invalidate(self, ctx: RunContext) -> None:
        super().invalidate(ctx)
        ctx.store.delete("transform_log.json")

    async def _new_story(self, ctx: RunContext, bible: Bible, spec: Spec) -> list[ChapterSummary]:
        src = bible.chapters
        cast = bible.render(max_entities=60)
        spec_txt = spec.render()
        lengths = ", ".join(f"ch. {c.index}: {c.word_count}" for c in src) or f"{spec.target_words}"
        n = len(src) or 1
        outline = await ctx.json(self.model_role, ROLE, [Part(ctx.prompts.render(
            "transform_story_new", chapters=n, lengths=lengths, spec=spec_txt, cast=cast))], _NewOutline,
            hints=ctx.hints(chapters=n), tag="transform:new_story")
        lines = {c.index: c for c in outline.chapters}
        outline_txt = "\n".join(f"Ch {c.index} {c.title}: {c.summary}" for c in outline.chapters)

        async def one(c: ChapterSummary) -> ChapterSummary:
            o = lines.get(c.index)
            line = f"{o.title}: {o.summary}" if o else "(continue the story)"
            out = await ctx.json(self.model_role, ROLE, [Part(ctx.prompts.render(
                "transform_chapter_new", index=c.index, words=c.word_count, outline=outline_txt, line=line,
                spec=spec.render(only=["plot_structure", "scene_sequence"]), cast=cast))], ChapterSummary,
                hints=ctx.hints(scenes=max(1, c.word_count // 500), events=3, index=c.index), tag=f"transform:new_ch{c.index}")
            out.index, out.word_count = c.index, c.word_count
            out.title = (o.title if o else "") or out.title
            out.summary = out.summary or (o.summary if o else "")
            for sc in out.scenes:
                sc.opening, sc.words, sc.dialogue, sc.sentence_words = "", 0, None, None
            return out

        return await gather_limited(src or [ChapterSummary(index=1, summary="", word_count=spec.target_words)], one,
                                    int(self.params.get("parallel", 8)))

    async def _regenerate_relations(self, ctx: RunContext, bible: Bible, char_pol: str, world_pol: str, spec_txt: str) -> None:
        """Replace the source's relationships where the dimension that owns them is replaced."""
        kinds = {e.id: e.kind for e in bible.entities}
        is_char = lambda i: kinds.get(i) == "character"  # noqa: E731

        def replaced(r: Relation) -> bool:
            both_chars = is_char(r.source) and is_char(r.target)
            return (char_pol == "regenerate" and both_chars) or (world_pol == "regenerate" and not both_chars)

        keep = [r for r in bible.relations if not replaced(r)]
        scope = ("Give relationships between characters" if char_pol == "regenerate" else "") + (
            (" and " if char_pol == "regenerate" else "Give ") + "ties of people to places, objects and organisations"
            if world_pol == "regenerate" else "") + "."
        listing = "\n".join(f"{e.id} | {e.name} [{e.kind}] — {e.description[:200]}" for e in bible.entities[:80])
        res = await ctx.json(self.model_role, ROLE, [Part(ctx.prompts.render("transform_relations", spec=spec_txt,
                                                                         entities=listing, scope=scope))], _Relations,
                             hints=ctx.hints(relations=0), tag="transform:relations")
        ok = set(kinds)
        new = [r for r in res.relations if r.source in ok and r.target in ok and r.source != r.target and replaced(r)]
        bible.relations = keep + new

    async def _rewrite_entities(self, ctx: RunContext, bible: Bible, char_pol: str, world_pol: str, spec_txt: str = "") -> None:
        batch = 30
        targets = bible.entities[: int(self.params.get("max_entities", 120))]

        def line(e: Entity) -> str:
            pol = char_pol if e.kind == "character" else world_pol
            if pol == "regenerate":  # replaced: the original description and role are not shown
                return f"{e.id} | {e.name} [{e.kind}] — (replaced: invent)"
            return (f"{e.id} | {e.name} [{e.kind}, {e.role}{', ' + e.gender if e.gender != 'unknown' else ''}] — "
                    f"{e.description[:400]}")

        async def one(group: list[Entity]):
            listing = "\n".join(line(e) for e in group)
            prompt = ctx.prompts.render("transform_entities", char_policy=char_pol, world_policy=world_pol, entities=listing,
                                        spec=spec_txt)
            out = await ctx.json(self.model_role, ROLE, [Part(prompt)], _EntityRewrites,
                                 hints=ctx.hints(entities=len(group)), tag="transform:entities")
            return out.entities

        groups = [targets[i : i + batch] for i in range(0, len(targets), batch)]
        results = await gather_limited(groups, one, 4)
        by_id = {r.id: r for rs in results for r in rs}
        for e in targets:
            if e.id in by_id:
                e.description = by_id[e.id].description or e.description
                e.role = by_id[e.id].role or e.role
