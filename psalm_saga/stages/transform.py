"""transform: source spec + bible -> synthetic spec + bible (clean-room boundary).

After this stage nothing downstream reads the source text: planning and drafting
see only the transformed spec and skeleton. That is the property the synthetic
corpus relies on, and it is what makes leakage measurable and attributable.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from psalm_saga.artifacts import Bible, ChapterSummary, DimensionSpec, Entity, Rename, Spec, TransformMap
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


def name_renames(tmap: TransformMap) -> TransformMap:
    """Keep only renames of proper-name forms that actually change something."""
    keep = [r for r in tmap.renames if r.original != r.new and is_name_form(r.original)]
    return TransformMap(renames=keep, setting_shift=tmap.setting_shift, notes=tmap.notes)


def complete_renames(tmap: TransformMap, entities: list[Entity]) -> TransformMap:
    """Make sure every name form (aliases, first/last name alone) has a replacement.

    Only proper-name forms are renamed (`is_name_form`); descriptive aliases such as "the mother"
    or "the girl" stay as they are, since they are not names and may refer to others."""
    tmap = name_renames(tmap)
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
        # Token-wise forms: "Deborah Jenkyns" -> "Deborah", "Jenkyns".
        if len(old_tokens) > 1:
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
            if rep == form:
                continue
            mapping[form] = rep
            lower[form.lower()] = rep
            out.append(Rename(original=form, new=rep, kind=e.kind, note=f"form of {e.name}"))
    return TransformMap(renames=_drop_composites(out), setting_shift=tmap.setting_shift, notes=tmap.notes)


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


def render_skeleton(ch: ChapterSummary) -> str:
    lines = [f"Chapter {ch.index}{(': ' + ch.title) if ch.title else ''} — {ch.word_count} words", f"Summary: {ch.summary}"]
    for i, s in enumerate(ch.scenes, 1):
        who = ", ".join(s.characters)
        lines.append(f"Scene {i}: {s.summary} | setting: {s.setting} | characters: {who} | purpose: {s.purpose} | pov: {s.pov}")
    for e in ch.events:
        cause = f" (because: {e.caused_by})" if e.caused_by else ""
        lines.append(f"Event: {e.description}{cause}")
    return "\n".join(lines)


@register("transform")
class Transform(Stage):
    modes = ("source",)
    outputs = ("transform.json", "spec.json", "bible.json")

    async def run(self, ctx: RunContext) -> None:
        policy = ctx.config.transform
        src_spec = ctx.store.read_json("spec_source.json", Spec)
        src_bible = ctx.store.read_json("bible_source.json", Bible)

        # 1. Names (an existing transform.json — e.g. hand-edited — is reused).
        if ctx.store.exists("transform.json"):
            tmap = complete_renames(ctx.store.read_json("transform.json", TransformMap), src_bible.entities)
        elif policy.rename_entities and src_bible.entities:
            listing = "\n".join(
                f"- {e.name} [{e.kind}{', ' + e.role if e.role else ''}{', ' + e.gender if e.gender != 'unknown' else ''}] aliases: {', '.join(e.aliases) or '-'} — {e.description[:200]}"
                for e in src_bible.entities[: int(self.params.get("max_entities", 120))]
            )
            prompt = ctx.prompts.render(
                "transform_names", entities=listing, keep_culture=policy.keep_cultural_setting,
                language=language_name(ctx.language), setting_policy=policy.policy.get("world_building", "abstract"),
                notes=policy.notes,
            )
            tmap = await ctx.json(self.model_role, ROLE, [Part(prompt)], TransformMap,
                                  hints=ctx.hints(renames=min(len(src_bible.entities), 6)), tag="transform:names")
            tmap = complete_renames(tmap, src_bible.entities)
            # Guarantee coverage: an entity the model skipped is flagged (kept), never silently leaked.
            missing = [e.name for e in src_bible.entities if is_name_form(e.name) and e.name not in tmap.as_dict()]
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

        # 3. Bible: entities and chapter skeletons.
        bible: Bible = rename_model(src_bible, mapping)  # type: ignore[assignment]
        bible.style_notes = []  # source-derived wording; the spec carries style now
        char_pol = policy.policy.get("character", "abstract")
        world_pol = policy.policy.get("world_building", "abstract")
        if bible.entities and (char_pol != "preserve" or world_pol != "preserve"):
            await self._rewrite_entities(ctx, bible, char_pol, world_pol)
        if any(policy.policy.get(k, "preserve") != "preserve" for k in ("scene_sequence", "world_building", "character")):
            spec_ex = spec.render(only=["scene_sequence", "world_building", "character"])

            async def reskin(ch: ChapterSummary) -> ChapterSummary:
                prompt = ctx.prompts.render("transform_skeleton", renames=renames_txt, setting_shift=tmap.setting_shift,
                                            spec=spec_ex, chapter=ch, skeleton=render_skeleton(ch))
                out = await ctx.json(self.model_role, ROLE, [Part(prompt)], ChapterSummary,
                                     hints=ctx.hints(scenes=len(ch.scenes), events=len(ch.events), index=ch.index),
                                     tag=f"transform:skeleton{ch.index}")
                if len(out.scenes) != len(ch.scenes):
                    ctx.emit("warning", stage="transform", message=f"chapter {ch.index}: re-skin changed scene count; kept renamed skeleton")
                    return ch
                out.index, out.word_count = ch.index, ch.word_count
                return out

            bible.chapters = await gather_limited(bible.chapters, reskin, int(self.params.get("parallel", 8)))
        ctx.store.write_json("bible.json", bible)

    async def _rewrite_entities(self, ctx: RunContext, bible: Bible, char_pol: str, world_pol: str) -> None:
        batch = 30
        targets = bible.entities[: int(self.params.get("max_entities", 120))]

        async def one(group: list[Entity]):
            listing = "\n".join(f"{e.id} | {e.name} [{e.kind}, {e.role}{', ' + e.gender if e.gender != 'unknown' else ''}] — {e.description[:400]}" for e in group)
            prompt = ctx.prompts.render("transform_entities", char_policy=char_pol, world_policy=world_pol, entities=listing)
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
