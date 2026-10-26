"""recover: extract a story bible from the finished synthetic text, with the same extractor
(and settings) that analysed the source, into `recovered/`.

This is measurement, not generation: it lets evaluation compare what the synthetic text
actually realises (characters, places, relations, scenes, causal links) with the source,
both seen through the same procedure (instrument KG), and it powers the web app's
"source vs synthetic text" graph comparison without a wait. One extraction pass; its cost
is booked under this stage, so it can be reported separately from generation cost.
"""

from __future__ import annotations

from dataclasses import replace

from psalm_saga.stages.base import RunContext, Stage, get_stage, register
from psalm_saga.store import RunStore


@register("recover")
class Recover(Stage):
    modes = ("source",)
    outputs = ("recovered/bible_source.json",)

    async def run(self, ctx: RunContext) -> None:
        story = ctx.store.read_text("story.md") if ctx.store.exists("story.md") else ""
        if not story.strip():
            ctx.emit("warning", stage="recover", message="no synthetic story to analyse")
            return
        await self._ensure_text_kind(ctx)
        await self._extract_into(ctx, "recovered", story, variant=0)
        if self.params.get("calibrate", True):
            # The same analysis run a second time on the source, as an independent sample: how far
            # the extractor agrees with itself is the ceiling for any graph comparison (instrument KG).
            await self._extract_into(ctx, "calibration", ctx.store.read_text("input/source.txt"), variant=2)

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

    def invalidate(self, ctx: RunContext) -> None:
        # The second analysis of the source depends only on the source: keep it when the synthetic
        # text is redone, so two versions of a run are measured against the same ceiling.
        ctx.store.delete("recovered")
        cal = ctx.store.root / "calibration" / "input" / "source.txt"
        src = ctx.store.root / "input" / "source.txt"
        if not (cal.exists() and src.exists() and cal.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")):
            ctx.store.delete("calibration")
