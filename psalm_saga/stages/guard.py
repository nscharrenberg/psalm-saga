"""guard: deterministic copyright-leakage check against the source, with targeted fixes.

1. Original names that slipped through are replaced from the rename table (no model call).
2. Paragraphs sharing a verbatim span of >= `min_span` words with the source are
   rewritten by the model, then re-checked once. Remaining spans are reported.
"""

from __future__ import annotations

from psalm_saga.artifacts import ChapterDraft, TransformMap
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, register
from psalm_saga.stages.review import Edits, apply_edits, split_paragraphs
from psalm_saga.stages.transform import apply_renames
from psalm_saga.text.chunking import word_count
from psalm_saga.text.metrics import SourceIndex, name_leakage

ROLE = "You are a careful line editor removing accidental verbatim overlap with a protected text."


@register("guard")
class Guard(Stage):
    modes = ("source",)
    outputs = ("guard.json",)

    async def run(self, ctx: RunContext) -> None:
        source = ctx.store.read_text("input/source.txt")
        tmap = ctx.store.maybe("transform.json", TransformMap) or TransformMap()
        mapping = {k: v for k, v in tmap.as_dict().items() if k != v}
        min_span = int(self.params.get("min_span", 10))
        index = SourceIndex(source, n=min(8, min_span))
        report = []
        for path in ctx.store.glob("chapters/ch_*.json"):
            name = path.relative_to(ctx.store.root).as_posix()
            d = ctx.store.read_json(name, ChapterDraft)
            c = d
            entry = {"chapter": d.index}
            leaked = name_leakage(list(mapping), d.text)
            if leaked:
                d.text = apply_renames(d.text, mapping)
                entry["names_replaced"] = leaked
            for attempt in range(int(self.params.get("rounds", 2))):
                paras = split_paragraphs(d.text)
                flagged = []
                for i, p in enumerate(paras, 1):
                    spans = index.spans(p, min_len=min_span)
                    if spans:
                        flagged.append((i, p, spans))
                if not flagged:
                    break
                entry[f"flagged_round{attempt}"] = [{"paragraph": i, "spans": [s["text"] for s in sp]} for i, _, sp in flagged]
                items = "\n\n".join(f"[P{i}] {p}\nOverlapping phrases: " + " | ".join(s["text"] for s in sp)
                                    for i, p, sp in flagged)
                edits = await ctx.json(self.model_role, ROLE, [Part(ctx.prompts.render("guard", items=items))], Edits,
                                       hints=ctx.hints(edits=0), tag=f"guard:ch{c.index}")
                d.text = "\n\n".join(apply_edits(paras, edits))
            remaining = index.spans(d.text, min_len=min_span)
            entry["remaining_spans"] = [s["text"] for s in remaining]
            d.word_count = word_count(d.text)
            ctx.store.write_json(name, d)
            report.append(entry)
        ctx.store.write_json("guard.json", {"min_span": min_span, "chapters": report})
