"""review: calibrated per-chapter check, with each problem fixed where it comes from.

Design choices against the over-critical loop of v1:
  * the reviewer only reports violations of *explicit* plan/spec commitments, with
    evidence, and is told an empty list is the normal outcome;
  * only issues at or above `threshold` (default: major) trigger a fix;
  * rounds are bounded (`rounds`, default 1) and a fix is kept only if the re-review
    finds no more blocking issues than before (`keep_if_not_worse`).

Routing. Every issue names its origin, and is fixed at that level:
  prose        the chapter fails a sound plan  -> paragraph-level repair of the chapter
  plan         the chapter follows a faulty plan -> the chapter plan is revised, the
               chapter redrafted from it and re-reviewed (`replan`, default on)
  spec, bible  plan and chapter follow a faulty specification or story bible -> after all
               chapters are reviewed, the spec / bible is amended once with all such issues
               and the run goes back to planning (`max_backtracks`, default 1; only issues at
               or above `backtrack_threshold`, default blocker). With no backtracks left the
               issues are recorded, not hidden.
A fixed workflow with a bounded backtrack, not an agent: the order of stages stays the same,
and every reroute is logged (reviews/ch_*.json, backtracks.json).
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from psalm_saga.artifacts import Bible, ChapterDraft, ChapterPlan, ChapterReview, Issue, Plan, Spec
from psalm_saga.llm import Part
from psalm_saga.stages.base import Backtrack, RunContext, Stage, gather_limited, get_stage, register
from psalm_saga.stages.conform import style_distance
from psalm_saga.stages.draft import clean_prose, draft_chapter_text, story_context
from psalm_saga.stages.plan import render_chapter_plan
from psalm_saga.text.chunking import word_count

ROLE_REVIEW = "You are a careful, fair editor checking a draft against its brief. You flag only real, checkable problems."
ROLE_REPAIR = "You are the novelist revising your own chapter with minimal, precise edits."
ROLE_REPLAN = "You are the novelist revising the plan of one chapter so that it is sound."
ROLE_AMEND = "You are the story's editor correcting the design document the story is written from."
SEVERITY = {"blocker": 0, "major": 1, "minor": 2}


def design_checklist(bible: Bible, c: ChapterPlan, max_items: int = 30) -> list[dict]:
    """The facts the story bible fixes for this chapter, as numbered items the reviewer accounts for
    one by one: events (E), causal links (C), relations between the people in the chapter (R) and
    the places and objects that belong to it (W)."""
    if not bible.entities and not bible.chapters:
        return []
    sk = next((ch for ch in bible.chapters if ch.index == c.index), None)
    items: list[dict] = []
    if sk:
        for e in sk.events:
            items.append({"kind": "event", "text": e.description})
        for e in sk.events:
            if e.caused_by:
                items.append({"kind": "cause", "text": f"{e.description} — because: {e.caused_by}"})
    names = {n.lower() for s in c.scenes for n in s.characters} | {n.lower() for s in (sk.scenes if sk else []) for n in s.characters}
    in_ch = {e.id for e in bible.entities
             if (e.kind == "character" and ({e.name.lower(), *(a.lower() for a in e.aliases)} & names))
             or (e.kind != "character" and c.index in e.chapters)}
    by_id = {e.id: e for e in bible.entities}
    rels = [r for r in bible.relations if r.source in in_ch and r.target in in_ch]
    for r in rels[:10]:
        a, b = by_id[r.source].name, by_id[r.target].name
        items.append({"kind": "relation", "text": f"{a} —{r.type}→ {b}" + (f" ({r.description})" if r.description else "")})
    world = sorted((by_id[i] for i in in_ch if by_id[i].kind != "character"), key=lambda e: -e.mentions)[:6]
    for e in world:
        items.append({"kind": "world", "text": f"{e.name} ({e.kind})" + (f": {e.description}" if e.description else "")})
    prefix = {"event": "E", "cause": "C", "relation": "R", "world": "W"}
    count: dict[str, int] = {}
    for it in items[:max_items]:
        k = prefix[it["kind"]]
        count[k] = count.get(k, 0) + 1
        it["id"] = f"{k}{count[k]}"
    return items[:max_items]


def coverage_issues(items: list[dict], rev: ChapterReview) -> list[Issue]:
    """Missing or contradicted checklist items, as issues routed like any other."""
    by_id = {it["id"]: it for it in items}
    out = []
    for cv in rev.coverage:
        it = by_id.get(cv.id.strip().upper())
        if not it or cv.status == "realised":
            continue
        core = it["kind"] in ("event", "cause")
        sev = "blocker" if (core and cv.status == "contradicted") else "major" if (core or cv.status == "contradicted") else "minor"
        fix = (f"Correct the chapter so that it agrees with: {it['text']}" if cv.status == "contradicted"
               else f"Show this in the chapter: {it['text']}")
        out.append(Issue(severity=sev, origin="prose" if cv.in_plan else "plan", dimension="bible",
                         commitment=f"[{it['id']}] {it['text']}", evidence=cv.evidence or cv.status, fix=fix))
    return out


def coverage_summary(items: list[dict], rev: ChapterReview) -> dict | None:
    if not items:
        return None
    st = {cv.id.strip().upper(): cv.status for cv in rev.coverage}
    ids = [it["id"] for it in items]
    return {"items": len(ids), "realised": sum(st.get(i) == "realised" for i in ids),
            "missing": [i for i in ids if st.get(i) == "missing"], "contradicted": [i for i in ids if st.get(i) == "contradicted"],
            "unanswered": [i for i in ids if i not in st]}


def issues_text(issues: list[Issue]) -> str:
    return "\n".join(f"- [{i.severity}, {i.origin}] {i.commitment}: {i.evidence} → fix: {i.fix}" for i in issues)


class Edit(BaseModel):
    paragraph: int = Field(description="Paragraph number to replace.")
    text: str = Field(description="Full new text of that paragraph (empty string deletes it).")


class Insert(BaseModel):
    insert_after: int
    text: str


class Edits(BaseModel):
    edits: list[Edit] = Field(default_factory=list)
    inserts: list[Insert] = Field(default_factory=list)


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def numbered(paras: list[str]) -> str:
    return "\n\n".join(f"[P{i}] {p}" for i, p in enumerate(paras, 1))


def apply_edits(paras: list[str], edits: Edits) -> list[str]:
    out = list(paras)
    for e in edits.edits:
        if 1 <= e.paragraph <= len(out):
            out[e.paragraph - 1] = clean_prose(re.sub(r"^\[P\d+\]\s*", "", e.text)) if e.text.strip() else ""
    for ins in sorted(edits.inserts, key=lambda x: -x.insert_after):
        pos = max(0, min(ins.insert_after, len(out)))
        out.insert(pos, clean_prose(ins.text))
    return [p for p in out if p.strip()]


async def repair_text(ctx: RunContext, stage: Stage, text: str, issues_txt: str, plan_txt: str, tag: str) -> str:
    mode = stage.params.get("repair_mode", "edits")
    paras = split_paragraphs(text)
    if mode == "rewrite":
        prompt = (f"Revise the chapter to fix these issues, keeping everything else. Output only the full revised prose.\n\n"
                  f"# Issues\n{issues_txt}\n\n# Plan\n{plan_txt}\n\n# Chapter\n{text}")
        return clean_prose(await ctx.text(stage.model_role, ROLE_REPAIR, [Part(prompt)],
                                          hints=ctx.hints(target_words=word_count(text)), tag=tag))
    prompt = ctx.prompts.render("repair", issues=issues_txt, plan=plan_txt, numbered=numbered(paras))
    edits = await ctx.json(stage.model_role, ROLE_REPAIR, [Part(prompt)], Edits,
                           hints=ctx.hints(edits=1, inserts=0, paragraph=1), tag=tag)
    return "\n\n".join(apply_edits(paras, edits))


@register("review")
class Review(Stage):
    outputs = ("reviews/ch_*.json",)

    def done(self, ctx: RunContext) -> bool:
        plan = ctx.store.maybe("plan.json", Plan)
        return bool(plan) and all(ctx.store.exists(f"reviews/ch_{c.index:03d}.json") for c in plan.chapters)

    async def check(self, ctx: RunContext, spec_txt: str, plan_txt: str, cast: str, text: str, index: int,
                    r: int, checklist: list[dict] | None = None) -> ChapterReview:
        max_issues = int(self.params.get("max_issues", 6))
        listing = "\n".join(f"{it['id']}. {it['text']}" for it in checklist or [])
        prompt = ctx.prompts.render("review", plan=plan_txt, text=text, max_issues=max_issues, cast=cast, checklist=listing)
        rev = await ctx.json(self.model_role, ROLE_REVIEW, [Part(spec_txt, cache=True), Part(prompt)], ChapterReview,
                             temperature=0.0, hints=ctx.hints(issues=0, coverage=0), tag=f"review:ch{index}r{r}")
        rev.index = index
        rev.issues = rev.issues[:max_issues] + coverage_issues(checklist or [], rev)
        return rev

    async def replan(self, ctx: RunContext, c: ChapterPlan, issues: list[Issue], spec_txt: str) -> ChapterPlan:
        prompt = ctx.prompts.render("replan", issues=issues_text(issues), plan=c.model_dump_json(indent=1))
        new = await ctx.json("plan", ROLE_REPLAN, [Part(spec_txt, cache=True), Part(prompt)], ChapterPlan,
                             hints=ctx.hints(scenes=len(c.scenes) or 1, beats=4), tag=f"replan:ch{c.index}")
        new.index, new.target_words = c.index, c.target_words
        new.title = new.title or c.title
        if not new.scenes:
            new.scenes = c.scenes
        return new

    async def run(self, ctx: RunContext) -> Backtrack | None:
        spec = ctx.store.read_json("spec.json", Spec)
        plan = ctx.store.read_json("plan.json", Plan)
        bible = ctx.store.maybe("bible.json", Bible) or Bible()
        rounds = int(self.params.get("rounds", 1))
        threshold = self.params.get("threshold", "major")
        allow_replan = bool(self.params.get("replan", True))
        spec_txt = spec.render()
        draft_stage = get_stage("draft", ctx.config.stages["draft"].impl or "chapter")(ctx.config.stages["draft"]) \
            if "draft" in ctx.config.stages else None
        plan_lock = asyncio.Lock()
        upstream: list[dict] = []

        async def one(c: ChapterPlan):
            name = f"reviews/ch_{c.index:03d}.json"
            if ctx.store.exists(name):
                upstream.extend(ctx.store.read_json(name).get("upstream", []))
                return
            draft = ctx.store.read_json(f"chapters/ch_{c.index:03d}.json", ChapterDraft)
            names = sorted({n for s in c.scenes for n in s.characters})
            cast = bible.render(names=names) if bible.entities else ""
            plan_txt = render_chapter_plan(c)
            checklist = design_checklist(bible, c) if self.params.get("coverage", True) else []
            history: list[dict] = []
            rev = await self.check(ctx, spec_txt, plan_txt, cast, draft.text, c.index, 0, checklist)
            history.append({"round": 0, "action": "review", **rev.model_dump()})
            self._report(ctx, c.index, 0, "review", rev, checklist, threshold)
            d_style = style_distance(ctx, draft.text)
            text, cur_plan, replanned = draft.text, c, False
            repairs_left, r = rounds, 0
            while True:  # one re-plan (if the plan is at fault) plus up to `rounds` prose repairs
                r += 1
                blocking = rev.blocking(threshold)
                plan_issues = [i for i in blocking if i.origin == "plan"]
                prose_issues = [i for i in blocking if i.origin == "prose"]
                if plan_issues and allow_replan and draft_stage is not None and not replanned:
                    # The plan is at fault: revise it, redraft the chapter from it, review again.
                    new_plan = await self.replan(ctx, cur_plan, plan_issues, spec_txt)
                    cand_text, _ = await draft_chapter_text(ctx, draft_stage, new_plan, plan, story_context(spec, plan),
                                                            bible, tag_suffix=f"r{r}")
                    new_plan_txt = render_chapter_plan(new_plan)
                    new_rev = await self.check(ctx, spec_txt, new_plan_txt, cast, cand_text, c.index, r, checklist)
                    kept = self._kept(new_rev, blocking, threshold)
                    self._report(ctx, c.index, r, "replan", new_rev, checklist, threshold, kept=kept)
                    history.append({"round": r, "action": "replan", "fixes": [i.model_dump() for i in plan_issues],
                                    "kept": kept, **new_rev.model_dump()})
                    replanned = True
                    if kept:
                        text, cur_plan, plan_txt, rev = cand_text, new_plan, new_plan_txt, new_rev
                        async with plan_lock:  # the revised chapter plan replaces the old one
                            p = ctx.store.read_json("plan.json", Plan)
                            p.chapters = [new_plan if x.index == c.index else x for x in p.chapters]
                            ctx.store.write_json("plan.json", p)
                            ctx.store.write_json(f"plan/ch_{c.index:03d}.json", new_plan)
                    continue
                if not prose_issues or repairs_left <= 0:
                    break
                repairs_left -= 1
                candidate = await repair_text(ctx, self, text, issues_text(prose_issues), plan_txt, f"repair:ch{c.index}r{r}")
                new_rev = await self.check(ctx, spec_txt, plan_txt, cast, candidate, c.index, r, checklist)
                kept = self._kept(new_rev, blocking, threshold)
                # A content repair must not undo the style work of conform (the data properties).
                d_new = style_distance(ctx, candidate)
                style_ok = d_style is None or d_new is None or d_new <= d_style + float(self.params.get("style_slack", 0.05))
                kept = kept and style_ok
                history.append({"round": r, "action": "repair", "fixes": [i.model_dump() for i in prose_issues],
                                "kept": kept, "style_distance": d_new, "style_ok": style_ok, **new_rev.model_dump()})
                self._report(ctx, c.index, r, "repair", new_rev, checklist, threshold, kept=kept,
                             style=None if d_new is None else round(d_new, 3))
                if not kept:
                    break
                text, rev = candidate, new_rev
                d_style = d_new if d_new is not None else d_style
            if text != draft.text:
                draft.text, draft.word_count = text, word_count(text)
                draft.attempts += 1
                ctx.store.write_json(f"chapters/ch_{c.index:03d}.json", draft)
            ups = [{"chapter": c.index, **i.model_dump()} for i in rev.issues if i.origin in ("spec", "bible")]
            upstream.extend(ups)
            ctx.store.write_json(name, {"index": c.index, "final_blocking": len(rev.blocking(threshold)),
                                        "replanned": replanned and cur_plan is not c, "upstream": ups,
                                        "checklist": checklist, "coverage": coverage_summary(checklist, rev),
                                        "rounds": history})

        await gather_limited(plan.chapters, one, int(self.params.get("parallel", 4)))
        return await self._backtrack(ctx, spec, bible, upstream)

    @staticmethod
    def _report(ctx: RunContext, index: int, r: int, action: str, rev: ChapterReview, checklist: list[dict],
                threshold: str, **extra) -> None:
        ctx.emit("review_result", stage="review", chapter=index, round=r, action=action,
                 blocking=len(rev.blocking(threshold)), coverage=coverage_summary(checklist, rev),
                 issues=[f"[{i.severity}, {i.origin}] {i.commitment}" for i in rev.issues], **extra)

    def _kept(self, new_rev: ChapterReview, blocking: list[Issue], threshold: str) -> bool:
        return not self.params.get("keep_if_not_worse", True) or len(new_rev.blocking(threshold)) <= len(blocking)

    async def _backtrack(self, ctx: RunContext, spec: Spec, bible: Bible, upstream: list[dict]) -> Backtrack | None:
        """Amend the spec / bible with the issues that originate there, and go back to planning."""
        limit = SEVERITY[self.params.get("backtrack_threshold", "blocker")]
        due = [u for u in upstream if SEVERITY[u["severity"]] <= limit]
        log = ctx.store.read_json("backtracks.json") if ctx.store.exists("backtracks.json") else []
        if not due:
            return None
        if len(log) >= int(self.params.get("max_backtracks", 1)):
            ctx.emit("warning", stage="review", message=f"{len(due)} issue(s) trace back to the spec/bible; no backtracks left")
            return None
        lines = "\n".join(f"- chapter {u['chapter']} [{u['severity']}, {u['origin']}] {u['commitment']}: {u['evidence']} "
                          f"→ {u['fix']}" for u in due)
        amended = []
        for origin, file, model, art in (("spec", "spec.json", Spec, spec), ("bible", "bible.json", Bible, bible)):
            mine = [u for u in due if u["origin"] == origin]
            if not mine or (origin == "bible" and not ctx.store.exists("bible.json")):
                continue
            prompt = ctx.prompts.render("amend", what="specification" if origin == "spec" else "story bible",
                                        issues=lines, artifact=art.model_dump_json(indent=1))
            new = await ctx.json("spec" if origin == "spec" else "plan", ROLE_AMEND, [Part(prompt)], model,
                                 hints=ctx.hints(), tag=f"amend:{origin}")
            ctx.store.write_json(file, new)
            amended.append(origin)
        if not amended:
            return None
        log.append({"attempt": len(log) + 1, "amended": amended, "issues": due})
        ctx.store.write_json("backtracks.json", log)
        return Backtrack("plan", f"{len(due)} issue(s) trace back to the {' and '.join(amended)}; amended, re-planning")
