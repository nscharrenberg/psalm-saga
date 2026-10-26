"""draft: chapters from the plan.

Context per call is scoped, not cumulative: spec (cached prefix) + the cast of this
chapter + this chapter's plan + either the previous chapter's planned ending
(`continuity: plan`, chapters run in parallel) or the tail of the previous prose
(`continuity: prose`, sequential). Prompt size stays flat however long the book is.
"""

from __future__ import annotations

import re

from psalm_saga.artifacts import Bible, ChapterDraft, ChapterPlan, Plan, Spec
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.stages.plan import render_chapter_plan
from psalm_saga.text.chunking import word_count
from psalm_saga.text.form import form_brief, form_profile, verse_budget
from psalm_saga.text.language import detect_language, language_name
from psalm_saga.text.style import rhythm_brief, rhythm_scaffold
from psalm_saga.text.variety import mismatch_note

ROLE = "You are an accomplished novelist writing in the voice and style the specification defines."

_LEAD_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s.*|\*\*[^*\n]{1,80}\*\*|(?:chapter|hoofdstuk|kapitel|chapitre|capítulo|capitolo|scene|scène|szene)\b[^\n]{0,80}|\[\[CHAPTER:[^\]]*\]\])\s*\n+",
    re.IGNORECASE,
)


def clean_prose(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?|```$", "", text).strip()
    for _ in range(3):
        new = _LEAD_HEADING.sub("", text, count=1)
        if new == text:
            break
        text = new.strip()
    text = re.sub(r"^\s*#{1,6}\s.*$", "", text, flags=re.MULTILINE)  # no headings anywhere
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def tail(text: str, words: int = 350) -> str:
    toks = text.split()
    return " ".join(toks[-words:])


def rhythm_block(ctx: RunContext, stage: Stage, chapter: ChapterPlan, total: int, target: int) -> str:
    """The measured form and rhythm of the source for this unit (numbers only).

    `stages.draft.params.rhythm`: "scaffold" (default: form + targets + a paragraph-by-paragraph
    scaffold), "brief" (form + targets), "off". Verse and drama get their form instructions instead
    of the prose scaffold."""
    st = ctx.style_targets
    mode = stage.params.get("rhythm", "scaffold" if stage.params.get("rhythm_targets", True) else "off")
    if not st or mode == "off":
        return ""
    form = st.get("form") or {}
    fb = form_brief(form)
    if form.get("form") == "verse":
        return f"{fb}\n{verse_budget(form, target)}"
    if form.get("form") == "drama":
        return fb
    out = rhythm_brief(st["stylometrics"], st["shape"])
    if mode == "scaffold":
        pos = (chapter.index - 1) / max(total, 1)
        out = f"{out}\n\n{rhythm_scaffold(st['shape'], target, pos)}".strip()
    return out


def _notes(params: dict) -> str:
    """The user's own instruction and, in a fixed version, the fix instruction (kept apart, so a fix
    replaces the previous version's fix instead of piling up on it)."""
    return "\n\n".join(x for x in (params.get("extra_instruction", ""), params.get("fix_instruction", "")) if x)


async def write_unit(ctx: RunContext, stage: Stage, *, spec_txt: str, cast: str, plan_txt: str, chapter: ChapterPlan,
                     total: int, target: int, unit: str, unit_name: str, prev_tail: str = "", prev_end: str = "",
                     tag: str = "") -> tuple[str, int]:
    """Write one chapter or scene; verify language and length. Returns (text, attempts)."""
    cfg = ctx.config.language
    variety = ctx.variety
    attempts, note = 0, ""
    text = ""
    rhythm = rhythm_block(ctx, stage, chapter, total, target)
    for attempts in range(1, cfg.max_retries + 2):
        prompt = ctx.prompts.render("draft", unit=unit, unit_name=unit_name, chapter=chapter, total_chapters=total,
                                    target_words=target, plan=plan_txt, prev_tail=prev_tail, prev_end=prev_end,
                                    variety=variety, language=language_name(ctx.language), rhythm=rhythm,
                                    extra=_notes(ctx.config.stages["draft"].params) if "draft" in ctx.config.stages else "")
        parts = [Part(spec_txt, cache=True), Part(cast), Part(prompt + note)]
        max_tokens = int(target * 2.2) + 600
        text = clean_prose(await ctx.text(stage.model_role, ROLE, parts, max_tokens=max_tokens,
                                          hints=ctx.hints(target_words=target, variant=attempts), tag=tag))
        if not cfg.enforce or word_count(text) < 20:
            break
        det = detect_language(text) if word_count(text) >= 120 else None  # too short to identify reliably
        if det is not None and det.code != ctx.language and det.confidence >= 0.35:
            ctx.emit("language_mismatch", tag=tag, expected=ctx.language, got=det.code, attempt=attempts)
            note = (f"\n\nIMPORTANT: a previous attempt was written in {language_name(det.code)}. "
                    f"Write this text in {language_name(ctx.language)} only.")
            continue
        # Right language; is it in the source's form (verse stays verse)?
        st = ctx.style_targets
        want = ((st or {}).get("form") or {}).get("form", "prose")
        if want in ("verse", "drama") and form_profile(text)["form"] != want:
            ctx.emit("form_mismatch", tag=tag, expected=want, attempt=attempts)
            note = (f"\n\nIMPORTANT: a previous attempt was written as prose. The source is {want}; write {want}"
                    + (", with line breaks, stanzas and rhyme as described above." if want == "verse" else "."))
            continue
        # Right language; is it also the right variety (dialect, historical spelling)?
        vnote = mismatch_note(text, variety, language_name(ctx.language)) if variety else None
        if vnote is not None:
            ctx.emit("variety_mismatch", tag=tag, variety=variety.name, attempt=attempts)
            note = "\n\n" + vnote
            continue
        # Right language, form and variety; is it far over budget? (A short text is topped up below;
        # a long one would carry its excess through every later stage.)
        wc = word_count(text)
        if wc > target * (1 + max(0.25, 2 * ctx.config.length.tolerance)) and attempts <= cfg.max_retries:
            ctx.emit("length_mismatch", tag=tag, target=target, got=wc, attempt=attempts)
            note = (f"\n\nIMPORTANT: a previous attempt had {wc} words; the budget is about {target}. Tell the same "
                    "beats more economically" + (" — fewer stanzas, not shorter lines." if want == "verse" else "."))
            continue
        break
    # Top up a clearly short text once, by continuation (cheaper than a rewrite).
    wc = word_count(text)
    if wc < target * (1 - ctx.config.length.tolerance) and stage.params.get("top_up", True):
        more = await ctx.text(stage.model_role, ROLE, [Part(spec_txt, cache=True), Part(cast), Part(
            f"{plan_txt}\n\nThe {unit_name} so far ({wc} words) is below its ~{target}-word budget. Continue it from "
            f"exactly where it stops, completing the remaining beats in about {target - wc} more words. Output only the "
            f"new prose.\n<so_far>\n{tail(text, 600)}\n</so_far>")],
            max_tokens=int((target - wc) * 2.2) + 400, hints=ctx.hints(target_words=target - wc), tag=f"{tag}:topup")
        text = f"{text}\n\n{clean_prose(more)}"
    return text, attempts


def chapter_cast(bible: Bible, c: ChapterPlan, max_world: int = 8) -> str:
    """The characters of this chapter's scenes plus the places and objects that belong to it, so
    the writer knows (and uses) their names; without the world entities the prose invents its own
    places and the story's settings are lost."""
    if not bible.entities:
        return ""
    names = {n for s in c.scenes for n in s.characters}
    text = " ".join(f"{s.setting} {s.summary}" for s in c.scenes).lower()
    world = [e for e in bible.entities if e.kind != "character"
             and (c.index in e.chapters or any(n.lower() in text for n in [e.name, *e.aliases] if len(n) > 3))]
    world.sort(key=lambda e: (-(e.name.lower() in text), -e.mentions))
    names |= {e.name for e in world[:max_world]}
    return bible.render(names=sorted(names))


def story_context(spec: Spec, plan: Plan) -> str:
    return spec.render() + f"\n\n# Whole-story arc\n{plan.arc}"


async def draft_chapter_text(ctx: RunContext, stage: Stage, c: ChapterPlan, plan: Plan, spec_txt: str, bible: Bible,
                             *, prev_tail: str = "", tag_suffix: str = "") -> tuple[str, int]:
    """Write one chapter from its plan (scene by scene when it is long). Returns (text, attempts).

    Used by the draft stage and by review when a chapter is re-planned and redrafted."""
    cast = chapter_cast(bible, c)
    total = len(plan.chapters)
    i = c.index - 1
    prev_end = plan.chapters[i - 1].ends_with or plan.chapters[i - 1].summary if i > 0 else ""
    max_words = ctx.config.length.max_chapter_words
    attempts = 0
    from psalm_saga.stages.review import design_checklist

    must = design_checklist(bible, c)
    facts = ("\n\n# Facts of the story design this chapter must show (in your own words)\n"
             + "\n".join(f"- {it['text']}" for it in must)) if must else ""
    if c.target_words <= max_words or len(c.scenes) <= 1:
        return await write_unit(ctx, stage, spec_txt=spec_txt, cast=cast, plan_txt=render_chapter_plan(c) + facts, chapter=c,
                                total=total, target=c.target_words, unit="this chapter", unit_name="chapter",
                                prev_tail=prev_tail, prev_end=prev_end, tag=f"draft:ch{c.index}{tag_suffix}")
    pieces: list[str] = []
    for j, s in enumerate(c.scenes, 1):
        one = ChapterPlan(index=c.index, title=c.title, pov=c.pov, summary=c.summary, scenes=[s],
                          commitments=c.commitments, ends_with=c.ends_with if j == len(c.scenes) else "")
        piece, a = await write_unit(
            ctx, stage, spec_txt=spec_txt, cast=cast,
            plan_txt=render_chapter_plan(one) + (facts.replace("this chapter must show", "this chapter must show (write those "
                                                               "that belong to this scene)") if facts else ""),
            chapter=c, total=total,
            target=s.target_words, unit=f"scene {j} of {len(c.scenes)} of this chapter", unit_name="scene",
            prev_tail=tail(pieces[-1]) if pieces else prev_tail, prev_end="" if pieces else prev_end,
            tag=f"draft:ch{c.index}s{j}{tag_suffix}")
        pieces.append(piece)
        attempts = max(attempts, a)
    return "\n\n".join(pieces), attempts


@register("draft", "chapter")
class DraftChapters(Stage):
    outputs = ("chapters/ch_*.json",)

    def done(self, ctx: RunContext) -> bool:
        plan = ctx.store.maybe("plan.json", Plan)
        return bool(plan) and all(ctx.store.exists(f"chapters/ch_{c.index:03d}.json") for c in plan.chapters)

    async def run(self, ctx: RunContext) -> None:
        spec = ctx.store.read_json("spec.json", Spec)
        plan = ctx.store.read_json("plan.json", Plan)
        bible = ctx.store.maybe("bible.json", Bible) or Bible()
        spec_txt = story_context(spec, plan)
        continuity = self.params.get("continuity", "plan")
        total = len(plan.chapters)
        drafts: dict[int, ChapterDraft] = {}

        async def chapter(c: ChapterPlan) -> ChapterDraft:
            name = f"chapters/ch_{c.index:03d}.json"
            if ctx.store.exists(name):
                return ctx.store.read_json(name, ChapterDraft)
            i = c.index - 1
            prev_tail = ""
            if continuity == "prose" and i > 0 and (i in drafts or ctx.store.exists(f"chapters/ch_{i:03d}.json")):
                prev = drafts.get(i) or ctx.store.read_json(f"chapters/ch_{i:03d}.json", ChapterDraft)
                prev_tail = tail(prev.text)
            ctx.emit("stage_progress", stage="draft", message=f"chapter {c.index}/{total}", chapter=c.index)
            text, attempts = await draft_chapter_text(ctx, self, c, plan, spec_txt, bible, prev_tail=prev_tail)
            d = ChapterDraft(index=c.index, title=c.title, text=text, word_count=word_count(text),
                             language=detect_language(text).code if word_count(text) >= 50 else ctx.language,
                             attempts=attempts)
            ctx.store.write_json(name, d)
            drafts[c.index] = d
            return d

        if continuity == "prose":
            for c in plan.chapters:
                await chapter(c)
        else:
            await gather_limited(plan.chapters, chapter, ctx.config.limits.max_parallel_chapters)
