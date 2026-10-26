"""assemble: chapters -> story.md / story.json. Headings are rendered here, in the
output language ("Hoofdstuk 3", "Kapitel 3"), never by the model."""

from __future__ import annotations

from psalm_saga.artifacts import ChapterDraft, Plan, Spec
from psalm_saga.stages.base import RunContext, Stage, register
from psalm_saga.text.language import label


def render_story(title: str, chapters: list[ChapterDraft], lang: str, *, numbered: bool = True) -> str:
    out = [f"# {title}".rstrip()] if title else []
    single = len(chapters) == 1
    for d in chapters:
        if not single:
            head = f"{label(lang, 'chapter')} {d.index}" if numbered else ""
            if d.title:
                head = f"{head}: {d.title}" if head else d.title
            out.append(f"## {head}")
        out.append(d.text.strip())
    return "\n\n".join(out).strip() + "\n"


@register("assemble")
class Assemble(Stage):
    outputs = ("story.md", "story.json")

    async def run(self, ctx: RunContext) -> None:
        plan = ctx.store.maybe("plan.json", Plan)
        spec = ctx.store.maybe("spec.json", Spec)
        files = ctx.store.glob("chapters/ch_*.json")
        chapters = [ChapterDraft.model_validate_json(p.read_text(encoding="utf-8")) for p in files]
        chapters.sort(key=lambda d: d.index)
        title = (plan.title if plan else "") or (spec.title if spec else "")
        form = ((ctx.style_targets or {}).get("form") or {})
        collection = form.get("form") == "verse" and (form.get("poem_titles") or 0) >= 3  # poems carry titles, not numbers
        numbered = self.params.get("numbered", not collection)
        md = render_story(title, chapters, ctx.language, numbered=numbered)
        ctx.store.write_text("story.md", md)
        ctx.store.write_json("story.json", {
            "title": title, "language": ctx.language,
            "word_count": sum(d.word_count for d in chapters),
            "chapters": [d.model_dump() for d in chapters],
        })
