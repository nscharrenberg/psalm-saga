"""plan: outline (one call) -> per-chapter scene plans (parallel, one call each).

Splitting the plan keeps every output small enough to be detailed, and a 40-chapter
novel no longer depends on one enormous generation finishing without truncation."""

from __future__ import annotations

from psalm_saga.artifacts import Bible, ChapterPlan, Outline, Plan, ScenePlan, Spec
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.stages.transform import render_skeleton

ROLE = "You are a novelist planning a story in detail before drafting it."


def _form_note(ctx: RunContext) -> str:
    """Plans for verse or drama are made for that form (a poem is planned in stanzas, not scenes of prose)."""
    from psalm_saga.text.form import form_brief

    fp = ((ctx.style_targets or {}).get("form")) or {}
    fb = form_brief(fp)
    if not fb:
        return ""
    unit = ("Plan each chapter as a poem: scenes are groups of stanzas, beats are what the stanzas tell, and word "
            "budgets follow the source's poem lengths." if fp.get("form") == "verse" else
            "Plan each scene as a scene of the play: who is on stage, what they say and do.")
    return f"{fb}\n{unit}"


def _budget(total: int, weights: list[float]) -> list[int]:
    s = sum(weights) or 1.0
    # A floor keeps a tiny chapter writable, but must not inflate a short text: three poems of a
    # 300-word source are not 3 x 150 words.
    floor = min(150, total // max(2 * len(weights), 1))
    return [max(floor, round(total * w / s)) for w in weights]


@register("plan")
class PlanStage(Stage):
    outputs = ("plan.json",)

    async def run(self, ctx: RunContext) -> None:
        spec = ctx.store.read_json("spec.json", Spec)
        bible = ctx.store.maybe("bible.json", Bible)
        skeletons = bible.chapters if bible and bible.chapters else []
        n = len(skeletons) or spec.chapters
        spec_txt = spec.render()
        skeleton_txt = "\n\n".join(render_skeleton(c) for c in skeletons)

        if ctx.store.exists("plan/outline.json"):
            outline = ctx.store.read_json("plan/outline.json", Outline)
        else:
            prompt = ctx.prompts.render("outline", chapters=n, target_words=spec.target_words, spec=spec_txt,
                                        skeleton=skeleton_txt, extra="\n\n".join(x for x in (self.params.get("extra_instruction", ""), self.params.get("fix_instruction", "")) if x),
                                        form=_form_note(ctx))
            outline = await ctx.json(self.model_role, ROLE, [Part(prompt)], Outline,
                                     hints=ctx.hints(chapters=n), tag="plan:outline")
            ctx.store.write_json("plan/outline.json", outline)

        chapters = list(outline.chapters)
        if skeletons and len(chapters) != len(skeletons):
            ctx.emit("warning", stage="plan", message=f"outline has {len(chapters)} chapters, skeleton {len(skeletons)}; aligning to skeleton")
            chapters = [chapters[i] if i < len(chapters) else ChapterPlan(index=i + 1, summary=s.summary, title="")
                        for i, s in enumerate(skeletons)]
        elif not skeletons and len(chapters) > n:
            chapters = chapters[:n]
        for i, c in enumerate(chapters):
            c.index = i + 1
        # Word budgets: follow source proportions when we have them, else the model's split.
        weights = [float(s.word_count or 1) for s in skeletons] if skeletons else [float(c.target_words or 1) for c in chapters]
        for c, w in zip(chapters, _budget(spec.target_words, weights), strict=True):
            c.target_words = w

        lines = [f"Ch {c.index} \"{c.title}\" ({c.target_words} words, POV {c.pov}): {c.summary}" for c in chapters]
        outline_ctx = f"{spec_txt}\n\n# Arc\n{outline.arc}\n\n# Chapter outline\n" + "\n".join(lines)
        if bible:
            outline_ctx += f"\n\n{bible.render()}"

        async def expand(c: ChapterPlan) -> ChapterPlan:
            name = f"plan/ch_{c.index:03d}.json"
            if ctx.store.exists(name):
                return ctx.store.read_json(name, ChapterPlan)
            i = c.index - 1
            sk = skeletons[i] if i < len(skeletons) else None
            prompt = ctx.prompts.render(
                "chapter_plan", chapter=c, arc=outline.arc, outline_line=lines[i],
                prev_end=chapters[i - 1].summary if i > 0 else "", next_line=lines[i + 1] if i + 1 < len(lines) else "",
                skeleton=render_skeleton(sk) if sk else "", extra="\n\n".join(x for x in (self.params.get("extra_instruction", ""), self.params.get("fix_instruction", "")) if x),
                form=_form_note(ctx),
            )
            hints = ctx.hints(scenes=len(sk.scenes) if sk and sk.scenes else 2, beats=4)
            full = await ctx.json(self.model_role, ROLE, [Part(outline_ctx, cache=True), Part(prompt)], ChapterPlan,
                                  hints=hints, tag=f"plan:ch{c.index}")
            full.index, full.title = c.index, full.title or c.title
            full.target_words, full.pov = c.target_words, full.pov or c.pov
            full.summary = full.summary or c.summary
            if not full.scenes:
                full.scenes = [ScenePlan(summary=full.summary)]
            for s, w in zip(full.scenes, _budget(c.target_words, [float(s.target_words or 1) for s in full.scenes]), strict=True):
                s.target_words = w
            ctx.store.write_json(name, full)
            return full

        expanded = await gather_limited(chapters, expand, int(self.params.get("parallel", 6)))
        ctx.store.write_json("plan.json", Plan(title=outline.title or spec.title, arc=outline.arc, chapters=expanded))

    def invalidate(self, ctx: RunContext) -> None:
        ctx.store.delete("plan.json")
        ctx.store.delete("plan")


def render_chapter_plan(c: ChapterPlan) -> str:
    out = [f"Chapter {c.index}: {c.title} (~{c.target_words} words, POV: {c.pov})", f"Summary: {c.summary}"]
    for i, s in enumerate(c.scenes, 1):
        out.append(f"\nScene {i} (~{s.target_words} words) — {s.summary}\nSetting: {s.setting}\nCharacters: {', '.join(s.characters)}\nPurpose: {s.purpose}")
        out += [f"  {j}. {b}" for j, b in enumerate(s.beats, 1)]
    if c.commitments:
        out.append("\nMust visibly realise:\n" + "\n".join(f"- {x}" for x in c.commitments))
    if c.ends_with:
        out.append(f"\nChapter ends with: {c.ends_with}")
    return "\n".join(out)
