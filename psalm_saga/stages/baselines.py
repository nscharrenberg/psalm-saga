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
        _save(ctx, pieces)


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
