"""recover: analyse the finished synthetic text once, and relate it back to the story design.

The synthetic text is analysed with the same extractor (and settings) that analysed the source,
into `recovered/`. The source is *not* analysed again: its graph exists already, and the design —
the source's bible after renaming and the policy — keeps the source's ids. The text's graph is
aligned with the design by rules and, for what the rules cannot pair, by model steps that pair
entities and scenes/events from their descriptions and finally check the synthetic chapters
themselves for design items the analysis did not find (psalm_saga.eval.kg_align). The alignment
(`recovered/alignment.json`) is what the evaluation (instrument KG), the graph comparison and the
targeted fixes use. Measurement, not generation: its cost is booked under this stage.

`calibrate: true` additionally analyses the source a second time, to estimate how far two analyses
of the same text agree (an optional noise ceiling for experiments).
"""

from __future__ import annotations

from dataclasses import replace

from psalm_saga.stages.base import RunContext, Stage, get_stage, register
from psalm_saga.store import RunStore


@register("recover")
class Recover(Stage):
    modes = ("source",)
    outputs = ("recovered/bible_source.json", "recovered/alignment.json")

    async def run(self, ctx: RunContext) -> None:
        story = ctx.store.read_text("story.md") if ctx.store.exists("story.md") else ""
        if not story.strip():
            ctx.emit("warning", stage="recover", message="no synthetic story to analyse")
            return
        await self._ensure_text_kind(ctx)
        await self._extract_into(ctx, "recovered", story, variant=0)
        await self._align(ctx)
        if self.params.get("calibrate", False):
            await self._extract_into(ctx, "calibration", ctx.store.read_text("input/source.txt"), variant=2)

    async def _align(self, ctx: RunContext) -> None:
        from psalm_saga.artifacts import Bible, ChapterDraft
        from psalm_saga.eval.kg_align import align_to_design

        design = ctx.store.maybe("bible.json", Bible)
        text = ctx.store.maybe("recovered/bible_source.json", Bible)
        if design is None or text is None:
            return
        chapters = {}
        for p in sorted(ctx.store.glob("chapters/ch_*.json")):
            d = ctx.store.read_json(f"chapters/{p.name}", ChapterDraft)
            chapters[d.index] = d.text
        mode = str(self.params.get("align", "model"))
        res = await align_to_design(ctx, design, text, chapters, use_model=mode == "model",
                                    check_text=bool(self.params.get("check_text", True)),
                                    role=self._extractor(ctx).model_role)
        ctx.store.write_json("recovered/alignment.json", res)
        st = res["stats"]
        ctx.emit("stage_progress", stage="recover",
                 message=f"aligned with the design: {st['rules']} by names, {st['model_entities'] + st['model_story']} by the "
                         f"model, {st['found_by_check']} of {st['checked']} unmatched items found by checking the text")

    async def _ensure_text_kind(self, ctx: RunContext) -> None:
        """Runs analysed before text kinds existed lack text_kind.json; evaluation needs it to know
        whether narrative measures apply (an essay has no cast). One short call, on the source."""
        if ctx.store.exists("text_kind.json") or not ctx.store.exists("input/source.txt"):
            return
        await self._extractor(ctx).classify(ctx, ctx.store.read_text("input/source.txt"))

    async def _extract_into(self, ctx: RunContext, folder: str, text: str, variant: int) -> None:
        sub = RunStore(ctx.store.root / folder)
        if sub.exists("bible_source.json") and sub.exists("input/source.txt") and sub.read_text("input/source.txt") == text:
            return
        for p in ("notes", "bible_source.json", "profile.json", "variety.json", "text_kind.json"):
            sub.delete(p)
        sub.write_text("input/source.txt", text)
        # Facts about the source that the graph does not depend on are copied, not re-asked.
        for f in ("variety.json", "text_kind.json"):
            if ctx.store.exists(f):
                sub.write_json(f, ctx.store.read_json(f))
        sub_ctx = replace(ctx, store=sub, state={"variant": variant} if variant else {})

        def emit(type_: str, **kw) -> None:  # progress shows up in the run's own event stream
            if kw.get("stage") == "extract":
                kw["stage"] = "recover"
                kw["message"] = f"{folder}: {kw.get('message', '')}".strip(": ")
            ctx.emit(type_, **kw)

        sub_ctx.emit = emit  # type: ignore[method-assign]
        await self._extractor(ctx).run(sub_ctx)

    @staticmethod
    def _extractor(ctx: RunContext) -> Stage:
        from psalm_saga.config import StageConfig

        ecfg = ctx.config.stages.get("extract")
        return get_stage("extract", ecfg.impl if ecfg else None)(ecfg or StageConfig())

    def done(self, ctx: RunContext) -> bool:
        # the text's analysis is reused when it is still current; the alignment is redone if missing
        return ctx.store.exists("recovered/bible_source.json") and ctx.store.exists("recovered/alignment.json")

    def invalidate(self, ctx: RunContext) -> None:
        # The second analysis of the source depends only on the source: keep it when the synthetic
        # text is redone, so two versions of a run are measured against the same ceiling.
        ctx.store.delete("recovered")
        cal = ctx.store.root / "calibration" / "input" / "source.txt"
        src = ctx.store.root / "input" / "source.txt"
        if not (cal.exists() and src.exists() and cal.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")):
            ctx.store.delete("calibration")
