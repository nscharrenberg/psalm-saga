from __future__ import annotations

from psalm_saga.eval.automatic import evaluate_run
from psalm_saga.stages.base import RunContext, Stage, register


@register("evaluate")
class Evaluate(Stage):
    """Fidelity/leakage report (evaluation.json). The automatic measures make no model calls; the two
    judges (`judges`, default on, model role `judge`) make two short calls on summaries and excerpts."""

    outputs = ("evaluation.json",)

    async def run(self, ctx: RunContext) -> None:
        report = evaluate_run(ctx.store, ctx.language)
        before = ctx.llm.usage.to_dict()
        from psalm_saga.eval.automatic import missing_reasons
        from psalm_saga.eval.grading import grades, suggest_fixes, summary_scores

        jcfg = ctx.config.judges
        if (jcfg.enabled or self.params.get("judges") is True) and ctx.store.exists("input/source.txt"):
            report["judges"] = await self._judges(ctx)
            fresh = missing_reasons(report, ctx.language)
            nm = report.setdefault("not_measurable", {})
            for k in ("judge_content", "judge_style", "psalm_fidelity", "psalm_expression"):
                if k in fresh and not str(nm.get(k, "")).startswith("not applicable: the source is"):
                    nm[k] = fresh[k]
                elif k not in fresh:
                    nm.pop(k, None)
        from psalm_saga.fixes import fix_context

        try:
            report["fix_context"] = fix_context(ctx.store)
        except Exception as exc:  # context for fixes is a convenience; never sink the evaluation
            report["fix_context"] = {"error": str(exc)[:300]}
        report["grades"] = grades(report)
        report["summary_scores"] = summary_scores(report)
        report["fixes"] = suggest_fixes(report)
        from psalm_saga.pipeline import _diff_usage, _sum_usage

        meta = ctx.store.meta()  # cumulative across resumes, up to the start of this stage
        report["evaluation_guided_fixes"] = meta.get("evaluation_guided_fixes", [])
        report["usage"] = _sum_usage(meta.get("usage", {}), _diff_usage(ctx.llm.usage.to_dict(), before))
        report["timing"] = meta.get("timing", {})
        ctx.store.write_json("evaluation.json", report)

    async def _judges(self, ctx: RunContext) -> dict:
        import asyncio

        from psalm_saga.artifacts import Bible, ChapterDraft, TransformMap
        from psalm_saga.config import ModelConfig
        from psalm_saga.eval.run_judges import content_judge, psalm_judge, style_judge

        jcfg = ctx.config.judges
        if jcfg.model:  # the judge model is configured separately from the writer's
            base = ctx.config.models.get("judge") or ctx.config.models["default"]
            ctx.config.models["judge"] = ModelConfig(**{**base.model_dump(), "name": jcfg.model, "temperature": 0.0,
                                                        "extra": {k: v for k, v in base.extra.items() if not k.startswith("fake_")}
                                                        if base.name != jcfg.model else base.extra})
        out: dict = {"model": ctx.config.model_for("judge").name}
        out["same_model_as_writer"] = out["model"] == ctx.config.model_for("draft").name
        policy = dict(ctx.config.transform.policy)
        tmap = ctx.store.maybe("transform.json", TransformMap)
        renames = tmap.as_dict() if tmap else {}
        src_bible = ctx.store.maybe("bible_source.json", Bible)
        rec = ctx.store.maybe("recovered/bible_source.json", Bible)
        source = ctx.store.read_text("input/source.txt")
        story = "\n\n".join(ctx.store.read_json(f"chapters/{p.name}", ChapterDraft).text
                             for p in sorted(ctx.store.glob("chapters/ch_*.json")))
        names = [*renames.keys(), *renames.values()]
        if src_bible:
            names += [n for e in src_bible.entities for n in [e.name, *e.aliases]]
        inst = set(jcfg.instruments or ["psalm", "content", "style"])

        async def safe(key: str, coro):
            try:
                out[key] = await coro
            except Exception as exc:  # a judge must not sink the evaluation
                out[key] = {"score": None, "reason_missing": f"the judge failed: {exc}"[:300]}

        jobs = []
        if "content" in inst:
            if src_bible and rec:
                jobs.append(safe("content", content_judge(ctx, src_bible, rec, renames, policy)))
            else:
                out["content"] = {"score": None, "reason_missing": "the synthetic text has not been analysed yet (stage recover)"}
        if "style" in inst:
            jobs.append(safe("style", style_judge(ctx, source, story, names, policy)))
        if "psalm" in inst:
            from psalm_saga.taxonomy import load_taxonomy

            jobs.append(safe("psalm", psalm_judge(ctx, load_taxonomy(ctx.config.taxonomy), source, story, src_bible, rec,
                                                  policy, jcfg)))
        await asyncio.gather(*jobs)
        return out
