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
            for k in ("judge_content", "judge_style", "psalm_fidelity", "psalm_expression", "psalm_residual"):
                if k in fresh and not str(nm.get(k, "")).startswith("not applicable: the source is"):
                    nm[k] = fresh[k]
                elif k not in fresh:
                    nm.pop(k, None)
        from psalm_saga.fixes import fix_context

        try:
            report["fix_context"] = fix_context(ctx.store)
        except Exception as exc:  # context for fixes is a convenience; never sink the evaluation
            report["fix_context"] = {"error": str(exc)[:300]}
        from psalm_saga.eval.grading import policy_exclusions
        from psalm_saga.priorities import describe, priority_score

        if ctx.mode == "source":
            report["policy"] = dict(ctx.config.transform.policy)
            report.setdefault("not_measurable", {}).update(policy_exclusions(report["policy"]))

        report["priorities"] = list(ctx.config.priorities)
        report["steering"] = describe(ctx.config.priorities)
        report["grades"] = grades(report)
        report["summary_scores"] = summary_scores(report)
        report["priority"] = priority_score(report["grades"], ctx.config.priorities)
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
        from psalm_saga.eval.run_judges import content_judge, psalm_judge, style_judge

        jcfg = ctx.config.judges
        if jcfg.model:  # the judge model is chosen separately from the writer's (a library name or a model id)
            ctx.config.models["judge"] = ctx.config.judge_model()
        out: dict = {"model": ctx.config.model_for("judge").name, "use": ctx.config.model_for("judge").use}
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
        if jcfg.panel:
            await self._panel(ctx, out, source, story, names, policy, renames, src_bible, rec, inst)
        return out

    async def _panel(self, ctx: RunContext, out: dict, source, story, names, policy, renames, src_bible, rec, inst) -> None:
        """Run the same judges on each further model of `judges.panel`, and report every judge's results
        and their agreement. The primary judge's results (above) stay the ones the grades use."""
        import asyncio

        from psalm_saga.eval.run_judges import content_judge, psalm_judge, style_judge
        from psalm_saga.eval.validity import judge_summary, panel_agreement
        from psalm_saga.taxonomy import load_taxonomy

        jcfg = ctx.config.judges
        members = []
        for i, mc in enumerate(ctx.config.panel_models(), 2):
            role = f"judge_{i}"
            ctx.config.models[role] = mc
            members.append((mc, _RoleContext(ctx, role)))

        async def one(mc, jctx):
            res: dict = {"model": mc.name, "use": mc.use}

            async def safe(key, coro):
                try:
                    res[key] = await coro
                except Exception as exc:  # one judge failing must not sink the others
                    res[key] = {"score": None, "reason_missing": f"the judge failed: {exc}"[:300]}

            jobs = []
            if "content" in inst and src_bible and rec:
                jobs.append(safe("content", content_judge(jctx, src_bible, rec, renames, policy)))
            if "style" in inst:
                jobs.append(safe("style", style_judge(jctx, source, story, names, policy)))
            if "psalm" in inst:
                jobs.append(safe("psalm", psalm_judge(jctx, load_taxonomy(ctx.config.taxonomy), source, story, src_bible,
                                                      rec, policy, jcfg)))
            await asyncio.gather(*jobs)
            return res

        panel = await asyncio.gather(*(one(m, j) for m, j in members))
        out["panel"] = panel
        primary = {"model": out["model"], "use": out.get("use"), **{k: out.get(k) for k in ("psalm", "content", "style")}}
        out["agreement"] = panel_agreement([primary, *panel])
        out["per_judge"] = [judge_summary(j) for j in (primary, *panel)]


class _RoleContext:
    """The run context with every judge call sent to another model role (one panel judge)."""

    def __init__(self, ctx: RunContext, role: str):
        self._ctx, self._role = ctx, role

    def __getattr__(self, item):
        return getattr(self._ctx, item)

    async def json(self, model_role, role_text, parts, schema, **kw):
        kw["tag"] = f"{kw.get('tag') or 'judge'}@{self._role}"
        return await self._ctx.json(self._role, role_text, parts, schema, **kw)

    async def text(self, model_role, role_text, parts, **kw):
        kw["tag"] = f"{kw.get('tag') or 'judge'}@{self._role}"
        return await self._ctx.text(self._role, role_text, parts, **kw)
