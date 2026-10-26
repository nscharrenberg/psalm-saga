"""spec: one detailed call per dimension instead of one giant call for all 36
sub-dimensions — more detail per sub-dimension, parallelisable, and individually
re-runnable. Source mode describes the source (parallel); premise mode decides
(sequential, each dimension sees the ones already decided)."""

from __future__ import annotations

from pydantic import BaseModel

from psalm_saga.artifacts import Bible, DimensionSpec, LanguageVariety, SourceProfile, Spec, SubSpec
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.text.chunking import split_chapters
from psalm_saga.text.metrics import describe_stylometrics
from psalm_saga.text.variety import resolve as resolve_variety


def _form_note(profile) -> str:
    from psalm_saga.text.form import form_brief

    fb = form_brief(getattr(profile, "form", None) or {})
    return f"\n{fb}" if fb else ""


ROLE_SOURCE = "You are a literary analyst writing a precise, checkable specification of an existing story."
ROLE_DECIDE = "You are a novelist designing a story before writing it: concrete, specific and consistent."


class _Header(BaseModel):
    title: str
    logline: str


def resolve_length(ctx: RunContext) -> tuple[int, int]:
    cfg = ctx.config.length
    profile = ctx.store.maybe("profile.json", SourceProfile)
    words = cfg.target_words or (profile.word_count if profile else 3000)
    if isinstance(cfg.chapters, int):
        chapters = cfg.chapters
    elif cfg.chapters == "match" and profile:
        chapters = len(profile.chapters)
    else:
        chapters = max(1, round(words / 3500))
    return words, max(1, chapters)


def excerpts(text: str, n: int = 3, words: int = 220) -> str:
    toks = text.split()
    if len(toks) <= n * words:
        return " ".join(toks[: n * words])
    starts = [int(len(toks) * f) for f in (0.08, 0.5, 0.85)][:n]
    return "\n...\n".join(" ".join(toks[s : s + words]) for s in starts)


def source_context(ctx: RunContext, bible: Bible) -> str:
    chapters = "\n".join(
        f"- Ch {c.index}{(' ' + c.title) if c.title else ''} ({c.word_count} words, {len(c.scenes)} scenes): {c.summary}"
        for c in bible.chapters
    )
    style = "\n".join(f"- {s}" for s in bible.style_notes)
    return f"# Story bible\n{bible.render()}\n\n# Chapters\n{chapters}\n\n# Style observations\n{style}"


@register("spec")
class SpecStage(Stage):
    outputs = ("spec.json",)

    def done(self, ctx: RunContext) -> bool:
        name = "spec_source.json" if ctx.mode == "source" else "spec.json"
        return ctx.store.exists(name)

    def invalidate(self, ctx: RunContext) -> None:
        ctx.store.delete("spec_source.json" if ctx.mode == "source" else "spec.json")

    async def run(self, ctx: RunContext) -> None:
        words, chapters = resolve_length(ctx)
        dims = ctx.taxonomy.dimensions
        if ctx.mode == "source":
            bible = ctx.store.read_json("bible_source.json", Bible)
            profile = ctx.store.read_json("profile.json", SourceProfile)
            context = source_context(ctx, bible)
            text = ctx.store.read_text("input/source.txt")
            style_dims = {"writing_style", "narrative_voice"}
            ex = excerpts(text)

            async def describe(dim):
                prompt = ctx.prompts.render(
                    "spec_dimension", mode="source", dim=dim,
                    stylometrics=(describe_stylometrics(profile.stylometrics) + _form_note(profile)) if dim.key == "writing_style" else "",
                    excerpts=ex if dim.key in style_dims else "",
                )
                return await self._dimension(ctx, ROLE_SOURCE, dim, [Part(context, cache=True), Part(prompt)])

            specs = await gather_limited(dims, describe, len(dims))
            spec = Spec(language=ctx.language, target_words=words, chapters=chapters, dimensions=specs,
                        variety=ctx.store.maybe("variety.json", LanguageVariety))
            # Chapter count of the source is a data point; keep the measured one.
            spec.chapters = len(split_chapters(text)) if ctx.config.length.chapters == "match" else chapters
            ctx.store.write_json("spec_source.json", spec)
            return

        premise = ctx.store.read_text("input/premise.md") if ctx.store.exists("input/premise.md") else ""
        given = ctx.store.maybe("input/spec.json", Spec) if ctx.mode == "spec" else None
        decided: list[DimensionSpec] = list(given.dimensions) if given else []
        for dim in dims:
            if any(d.dimension == dim.key for d in decided):
                continue
            so_far = Spec(language=ctx.language, target_words=words, chapters=chapters, dimensions=decided,
                          title=given.title if given else "", logline=given.logline if given else "").render()
            prompt = ctx.prompts.render("spec_dimension", mode="decide", dim=dim)
            ctxt = f"# Premise\n{premise or (given.logline if given else '')}\n\n# Decided so far\n{so_far}"
            decided.append(await self._dimension(ctx, ROLE_DECIDE, dim, [Part(ctxt), Part(prompt)]))
        title, logline = (given.title, given.logline) if given and given.title else ("", "")
        if not title:
            hdr = await ctx.json(self.model_role, ROLE_DECIDE,
                                 [Part(f"# Premise\n{premise}\n\n{Spec(language=ctx.language, target_words=words, chapters=chapters, dimensions=decided).render()}"),
                                  Part("Give the story a title and a one-sentence logline, in the output language.")],
                                 _Header, hints=ctx.hints(), tag="spec:header")
            title, logline = hdr.title, hdr.logline
        spec = Spec(language=ctx.language, title=title, logline=logline,
                    target_words=given.target_words if given and ctx.config.length.target_words is None else words,
                    chapters=given.chapters if given and not isinstance(ctx.config.length.chapters, int) else chapters,
                    dimensions=decided,
                    variety=resolve_variety(ctx.config.language.variety, given.variety if given else None,
                                            ctx.config.transform.policy.get("writing_style", "preserve")))
        ctx.store.write_json("spec.json", spec)

    async def _dimension(self, ctx: RunContext, role: str, dim, parts) -> DimensionSpec:
        keys = [s.key for s in dim.subdimensions]
        out = await ctx.json(self.model_role, role, parts, DimensionSpec,
                             hints=ctx.hints(items=len(keys), dimension=dim.key), tag=f"spec:{dim.key}")
        out.dimension = dim.key
        # Keep exactly the taxonomy's keys, in order; fill any the model skipped.
        by_key = {i.key: i for i in out.items}
        fixed = []
        for i, k in enumerate(keys):
            item = by_key.get(k) or (out.items[i] if i < len(out.items) and out.items[i].key not in keys else None)
            if item is None:
                item = SubSpec(key=k, value="(not specified)")
            item.key = k
            fixed.append(item)
        out.items = fixed
        return out


@register("spec", "none")
class NoSpec(SpecStage):
    """Ablation: a spec with length and header only, no dimension commitments."""

    async def run(self, ctx: RunContext) -> None:
        words, chapters = resolve_length(ctx)
        spec = Spec(language=ctx.language, target_words=words, chapters=chapters, dimensions=[],
                    logline=(ctx.store.read_text("input/premise.md")[:600] if ctx.store.exists("input/premise.md") else ""),
                    variety=ctx.store.maybe("variety.json", LanguageVariety) if ctx.mode == "source" else None)
        ctx.store.write_json("spec_source.json" if ctx.mode == "source" else "spec.json", spec)
