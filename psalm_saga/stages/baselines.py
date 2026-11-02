"""Baseline `draft` implementations, selectable from a preset:

  draft: {impl: oneshot, params: {inputs: [spec, skeleton]}}   # C3 flat + spec
  draft: {impl: oneshot, params: {inputs: [source]}}           # C5 flat (rewrite the source in one call)
  draft: {impl: paraphrase}                                    # chunk-wise paraphrase of the source
  draft: {impl: agents_room}                                   # Agents' Room (Huot et al., 2024)
"""

from __future__ import annotations

import re

from psalm_saga.artifacts import Bible, ChapterDraft, Spec, TransformMap
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.stages.draft import clean_prose
from psalm_saga.stages.transform import render_skeleton
from psalm_saga.text.chunking import chunk_chapters, split_chapters, word_count
from psalm_saga.text.language import detect_language

ROLE = "You are an accomplished novelist."
_MARK = re.compile(r"^\s*\[\[CHAPTER:\s*(.*?)\]\]\s*$", re.MULTILINE)


def _save(ctx: RunContext, pieces: list[tuple[str, str]], attempts: int = 1) -> None:
    ctx.store.delete("chapters/ch_*.json")
    for i, (title, text) in enumerate(pieces, 1):
        text = clean_prose(text)
        lang = detect_language(text).code if word_count(text) >= 50 else ctx.language
        ctx.store.write_json(f"chapters/ch_{i:03d}.json", ChapterDraft(index=i, title=title, text=text,
                                                                       word_count=word_count(text), language=lang,
                                                                       attempts=attempts))


_DIM = {"writing_style": "writing style", "narrative_voice": "narrative voice", "character": "characters",
        "plot_structure": "plot structure", "scene_sequence": "sequence of scenes", "world_building": "world and setting"}
_DO = {"preserve": "keep it as in the source, with the same particulars (new names only)",
       "abstract": "keep what it does in the story (its role, function and structure) but invent new concrete "
                   "particulars for it",
       "regenerate": "replace it with something new of your own; do not follow the source here"}


def policy_brief(policy: dict[str, str]) -> str:
    """The per-dimension policy as instructions for a single-call baseline; empty when everything is
    kept (the prompt's default wording then applies)."""
    if all(v == "preserve" for v in policy.values()):
        return ""
    return "\n".join(f"- {_DIM.get(k, k)}: {_DO.get(v, v)}" for k, v in policy.items())


def _premise(ctx: RunContext) -> str:
    if ctx.store.exists("input/premise.md"):
        return ctx.store.read_text("input/premise.md")
    spec = ctx.store.maybe("spec.json", Spec)
    return spec.logline if spec else ""


@register("draft", "oneshot")
class OneShot(Stage):
    outputs = ("chapters/ch_*.json",)

    async def run(self, ctx: RunContext) -> None:
        inputs = set(self.params.get("inputs", ["spec"]))
        spec = ctx.store.maybe("spec.json", Spec)
        bible = ctx.store.maybe("bible.json", Bible)
        words = spec.target_words if spec else int(ctx.config.length.target_words or 3000)
        chapters = spec.chapters if spec else 1
        source = ""
        if "source" in inputs and ctx.store.exists("input/source.txt"):
            source = ctx.store.read_text("input/source.txt")
            if not spec:
                words = ctx.config.length.target_words or word_count(source)
                chapters = len(split_chapters(source))
            budget = int(ctx.config.model_for(self.model_role).context_window * 0.6 * 3)  # ~chars
            if len(source) > budget:
                ctx.emit("warning", stage="draft", message=f"source truncated to fit context ({len(source)} -> {budget} chars)")
                source = source[:budget]
        spec_txt = spec.render() if spec and "spec" in inputs else ""
        if spec_txt and "skeleton" in inputs and bible:
            spec_txt += "\n\n# Chapter skeleton\n" + "\n\n".join(render_skeleton(c) for c in bible.chapters)
        prompt = ctx.prompts.render("oneshot", target_words=words, chapters=chapters, source=source, spec=spec_txt,
                                    policy=policy_brief(dict(ctx.config.transform.policy)) if source else "",
                                    premise=_premise(ctx) if "premise" in inputs or not (source or spec_txt) else "")
        mc = ctx.config.model_for(self.model_role)
        text = await ctx.text(self.model_role, ROLE, [Part(prompt)], max_tokens=mc.max_output_tokens,
                              hints=ctx.hints(target_words=words), tag="draft:oneshot",
                              continuations=int(self.params.get("continuations", 3)))
        marks = list(_MARK.finditer(text))
        if marks:
            pieces = [(m.group(1).strip(), text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)])
                      for i, m in enumerate(marks)]
            pre = text[: marks[0].start()].strip()
            if pre:
                pieces[0] = (pieces[0][0], pre + "\n\n" + pieces[0][1])
        else:
            pieces = [("", text)]
        # Compute-matched variant: spend more inference on the same single-step approach by letting the
        # model critique and revise its own text against the source (self-refinement, Madaan et al. 2023).
        rounds = int(self.params.get("refine_rounds", 0))
        for r in range(1, rounds + 1):
            pieces = await self._refine(ctx, pieces, source, spec_txt, words, r)
        _save(ctx, pieces, attempts=1 + rounds)

    async def _refine(self, ctx: RunContext, pieces: list[tuple[str, str]], source: str, spec_txt: str, words: int,
                      r: int) -> list[tuple[str, str]]:
        text = "\n\n".join((f"[[CHAPTER: {t}]]\n" if t or len(pieces) > 1 else "") + b for t, b in pieces)
        brief = (f"# Source\n{source}" if source else "") + (f"\n\n# Specification\n{spec_txt}" if spec_txt else "")
        critique = await ctx.text(self.model_role, ROLE, [Part(
            "Review this synthetic counterpart against what it must achieve: the same structure, characters and their "
            "relations, narrative voice and style as the source, in the source's language and length (about "
            f"{words} words), but with new names and none of the source's wording or distinctive particulars where they "
            "should change. List the most important problems, concretely, each with where it occurs.\n\n"
            f"{brief}\n\n# Synthetic text\n{text}")], max_tokens=2000, hints=ctx.hints(round=r), tag=f"draft:critique:r{r}")
        mc = ctx.config.model_for(self.model_role)
        revised = await ctx.text(self.model_role, ROLE, [Part(
            "Revise the synthetic text to fix these problems, keeping everything else. Output the full revised text, "
            "with the same [[CHAPTER: title]] markers if it has them.\n\n"
            f"# Problems\n{critique}\n\n{brief}\n\n# Synthetic text\n{text}")], max_tokens=mc.max_output_tokens,
            hints=ctx.hints(target_words=words, round=r), tag=f"draft:refine:r{r}",
            continuations=int(self.params.get("continuations", 3)))
        marks = list(_MARK.finditer(revised))
        if not marks:
            return [("", revised)]
        return [(m.group(1).strip(), revised[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(revised)])
                for i, m in enumerate(marks)]


@register("draft", "paraphrase")
class Paraphrase(Stage):
    """Naive synthetic-corpus baseline: paraphrase the source passage by passage."""

    modes = ("source",)
    outputs = ("chapters/ch_*.json",)

    async def run(self, ctx: RunContext) -> None:
        source = ctx.store.read_text("input/source.txt")
        tmap = ctx.store.maybe("transform.json", TransformMap) or TransformMap()
        renames = "; ".join(f"{k} → {v}" for k, v in tmap.as_dict().items()) or "(keep names)"
        chapters = split_chapters(source)
        chunks = chunk_chapters(chapters, chunk_words=int(self.params.get("chunk_words", 700)))

        async def one(ch):
            out = await ctx.text(self.model_role, ROLE, [Part(ctx.prompts.render("paraphrase", renames=renames, text=ch.text))],
                                 max_tokens=int(ch.words * 2.5) + 300, hints=ctx.hints(target_words=ch.words),
                                 tag=f"draft:paraphrase{ch.index}")
            return ch, clean_prose(out)

        results = await gather_limited(chunks, one, int(self.params.get("parallel", 8)))
        by_ch: dict[int, list[str]] = {}
        for ch, text in results:
            by_ch.setdefault(ch.chapter, []).append(text)
        _save(ctx, [("", "\n\n".join(by_ch.get(c.index, []))) for c in chapters])


_PLANNERS = [
    ("conflict", "the central conflict, what is at stake, and how it escalates"),
    ("character", "the main characters: their traits, goals, relationships and arcs"),
    ("setting", "the setting: places, period, atmosphere and any world rules"),
    ("plot", "the plot: the key events in order, from opening to resolution"),
]
_WRITERS = ["exposition", "rising action", "climax", "falling action", "resolution"]
_WEIGHTS = [0.2, 0.3, 0.2, 0.15, 0.15]


@register("draft", "agents_room")
class AgentsRoom(Stage):
    """Agents' Room with its fixed orchestration: four planners fill a shared scratchpad,
    then five writers produce the story section by section."""

    outputs = ("chapters/ch_*.json",)

    async def run(self, ctx: RunContext) -> None:
        spec = ctx.store.maybe("spec.json", Spec)
        bible = ctx.store.maybe("bible.json", Bible)
        premise = _premise(ctx)
        if spec and self.params.get("use_spec", True):
            premise = spec.render()
            if bible and bible.chapters:
                premise += "\n\n# Chapter skeleton\n" + "\n\n".join(render_skeleton(c) for c in bible.chapters)
        words = spec.target_words if spec else int(ctx.config.length.target_words or 3000)
        pad: list[str] = []
        for agent, task in _PLANNERS:
            entry = await ctx.text(self.model_role, ROLE, [Part(ctx.prompts.render(
                "agents_room_plan", agent=agent, task=task, premise=premise, scratchpad="\n\n".join(pad)))],
                hints=ctx.hints(target_words=200), tag=f"agents_room:{agent}")
            pad.append(f"## {agent}\n{entry}")
        story: list[str] = []
        for agent, w in zip(_WRITERS, _WEIGHTS, strict=True):
            target = max(100, int(words * w))
            sec = await ctx.text(self.model_role, ROLE, [Part(ctx.prompts.render(
                "agents_room_write", agent=agent, target_words=target, premise=premise, scratchpad="\n\n".join(pad),
                story="\n\n".join(story)))], max_tokens=int(target * 2.2) + 400,
                hints=ctx.hints(target_words=target), tag=f"agents_room:{agent.replace(' ', '_')}")
            story.append(clean_prose(sec))
        ctx.store.write_text("agents_room_scratchpad.md", "\n\n".join(pad))
        _save(ctx, [("", "\n\n".join(story))])
