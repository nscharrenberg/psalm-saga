"""conform: bring each drafted chapter's rhythm onto the source's measured targets.

Drafting prompts state the targets, but models drift back to their own register (short
sentences, one-line paragraphs, invented dialogue). This stage measures every chapter
deterministically and, when it is off target, asks for a *layout and rhythm* revision with the
measured numbers and concrete operations (join sentences, merge paragraphs, report speech): the
same events, details, names, language and variety. A revision is kept only if it moves the
chapter closer to the targets without changing its length by more than `max_length_change`
or losing language-variety forms; a rejected attempt is retried while `rounds` remain
(default 2).

What is steered is listed in text/style.py (TARGET_KEYS: sentence and paragraph length,
dialogue share, punctuation rates). The function-word profile, character n-grams and full
distributions are not steered, so evaluation keeps independent evidence of style; the ablation
`stages.conform.enabled=false` measures what the stage contributes. Only numbers from the
source profile are used, so the clean-room boundary holds.
"""

from __future__ import annotations

import re

from psalm_saga.artifacts import ChapterDraft
from psalm_saga.llm import Part
from psalm_saga.stages.base import RunContext, Stage, gather_limited, register
from psalm_saga.stages.draft import clean_prose
from psalm_saga.text.chunking import word_count
from psalm_saga.text.language import detect_language, language_name
from psalm_saga.text.style import (
    VERSE_KEYS,
    distance,
    measure,
    rhythm_scaffold,
    shape,
    style_gaps,
    target_keys,
    verse_gaps,
    verse_target,
)
from psalm_saga.text.variety import variety_share


def variety_gap(text: str, variety) -> str | None:
    """A gap line when the chapter drifted toward the standard language (historical spelling or
    dialect forms replaced by modern ones), naming the forms to restore."""
    if not variety or variety.standard or not variety.markers or variety.source_share is None:
        return None
    m = variety_share(text, variety, min_hits=3)
    if not m or m["share"] is None or m["share"] >= variety.source_share - 0.2:
        return None
    pairs = [mk for mk in variety.markers if mk.standard_form in m.get("top_standard_forms", [])][:8]
    ex = "; ".join(f"“{p.variety_form}” instead of “{p.standard_form}”" for p in pairs)
    return (f"Only {round(100 * m['share'])}% of the forms that have a {variety.name} variant use it; in the source "
            f"{round(100 * variety.source_share)}% do. Restore them" + (f": {ex}" if ex else "") + ".")

ROLE = ("You are the novelist revising the rhythm and layout of your own chapter to match a measured style, "
        "changing how things are said, never what happens.")


def passages(text: str, words: int) -> list[str]:
    """Split on paragraph boundaries into pieces of about `words` words."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out


def _table(measured: dict, target: dict, keys: tuple[str, ...]) -> str:
    names = {"mean_sentence_words": "words per sentence (mean)", "sd_sentence_words": "words per sentence (spread)",
             "mean_paragraph_words": "words per paragraph (mean)", "dialogue_paragraph_share": "share of paragraphs with dialogue",
             "dialogue_word_share": "share of words in direct speech",
             "line_words_mean": "words per verse line (mean)", "lines_per_stanza_mean": "lines per stanza (mean)",
             "rhyme_share": "share of rhyming lines",
             "commas_per_1k": "commas per 1,000 words", "question_sentence_share": "share of questions",
             "exclamation_sentence_share": "share of exclamations"}
    rows = [f"| {names[k]} | {measured.get(k, 0):g} | {target.get(k, 0):g} |" for k in keys]
    return "| measure | this chapter | target |\n|---|---|---|\n" + "\n".join(rows)


def style_distance(ctx: RunContext, text: str) -> float | None:
    """Distance of a text from the source's measured style (the number conform minimises), or None
    when there are no style targets (no source) or the form has none (drama)."""
    targets = ctx.style_targets or {}
    if not targets:
        return None
    fp = targets.get("form") or {"form": "prose"}
    form = fp.get("form", "prose")
    if form == "drama":
        return None
    verse = form == "verse"
    target = verse_target(targets.get("stylometrics") or {}, fp) if verse else (targets.get("stylometrics") or {})
    keys = VERSE_KEYS if verse else target_keys(target)
    return distance(measure(text, ctx.language, form), target, keys)


@register("conform")
class Conform(Stage):
    modes = ("source",)
    outputs = ("conform/ch_*.json",)

    def applies(self, ctx: RunContext) -> bool:
        return super().applies(ctx) and ctx.style_targets is not None

    @staticmethod
    def _chapters(ctx: RunContext) -> list[int]:
        return sorted(int(p.stem.split("_")[1]) for p in ctx.store.glob("chapters/ch_*.json"))

    def done(self, ctx: RunContext) -> bool:
        idx = self._chapters(ctx)
        return bool(idx) and all(ctx.store.exists(f"conform/ch_{i:03d}.json") for i in idx)

    async def run(self, ctx: RunContext) -> None:
        targets = ctx.style_targets or {}
        fp = targets.get("form") or {"form": "prose"}
        form = fp.get("form", "prose")
        if form == "drama":  # speaker-labelled text: layout operations would break the format
            for i in self._chapters(ctx):
                ctx.store.write_json(f"conform/ch_{i:03d}.json", {"index": i, "skipped": "drama"})
            return
        verse = form == "verse"
        n_ch = max(len(self._chapters(ctx)), 1)
        span = 1 / n_ch  # share of the book one chapter covers, to place the scaffold
        target = verse_target(targets.get("stylometrics") or {}, fp) if verse else (targets.get("stylometrics") or {})
        keys = VERSE_KEYS if verse else target_keys(target)
        tol = float(self.params.get("tolerance", 0.12))
        rounds = int(self.params.get("rounds", 2))
        max_change = float(self.params.get("max_length_change", 0.12))
        piece_words = int(self.params.get("passage_words", 1800))
        variety = ctx.variety

        async def revise(text: str, measured: dict, gaps: list[str], tag: str, attempt: int, position: float) -> str:
            pieces = passages(text, piece_words)
            offsets, acc = [], 0
            for pc in pieces:
                offsets.append(acc / max(word_count(text), 1))
                acc += word_count(pc)

            async def one(args) -> str:
                k, piece = args
                scaffold = "" if verse else rhythm_scaffold(targets.get("shape") or {}, word_count(piece),
                                                            position + offsets[k] * span)
                prompt = ctx.prompts.render("conform_verse" if verse else "conform", table=_table(measured, target, keys),
                                            gaps=gaps, text=piece, scaffold=scaffold,
                                            words=word_count(piece), language=language_name(ctx.language), variety=variety)
                return clean_prose(await ctx.text(self.model_role, ROLE, [Part(prompt)],
                                                  max_tokens=int(word_count(piece) * 2.4) + 400,
                                                  hints=ctx.hints(target_words=word_count(piece), variant=attempt),
                                                  tag=tag))

            out = await gather_limited(list(enumerate(pieces)), one, int(self.params.get("parallel", 4)))
            return "\n\n".join(o for o in out if o.strip())

        async def chapter(i: int):
            name = f"conform/ch_{i:03d}.json"
            if ctx.store.exists(name):
                return
            path = f"chapters/ch_{i:03d}.json"
            draft = ctx.store.read_json(path, ChapterDraft)
            text, m = draft.text, measure(draft.text, ctx.language, form)
            d0 = d = distance(m, target, keys) + (0.5 if verse and m.get("form") != "verse" else 0)
            log = {"index": i, "form": form, "tolerance": tol, "before": {k: m.get(k) for k in keys}, "distance_before": d0,
                   "rounds": []}
            v0 = (variety_share(text, variety, min_hits=3) or {}).get("share") if variety else None
            for r in range(1, rounds + 1):
                vnote = variety_gap(text, variety)
                if (d <= tol and not vnote) or word_count(text) < 80:
                    break
                gaps = verse_gaps(m, target, fp) if verse else style_gaps(
                    m, target, shp_target=targets.get("shape"), shp_measured=shape(text))
                if vnote:
                    gaps = [*gaps, vnote]
                if not gaps:
                    break
                cand = await revise(text, m, gaps, f"conform:ch{i}r{r}", r, (i - 1) / n_ch)  # variant: a new sample
                cm = measure(cand, ctx.language, form)
                cd = distance(cm, target, keys) + (0.5 if verse and cm.get("form") != "verse" else 0)
                change = abs(word_count(cand) - word_count(draft.text)) / max(word_count(draft.text), 1)
                ok_lang = word_count(cand) < 120 or detect_language(cand).code == ctx.language
                ok_var = True
                vs = None
                if variety and v0 is not None:
                    vs = (variety_share(cand, variety, min_hits=3) or {}).get("share")
                    ok_var = vs is not None and vs >= v0 - 0.1  # no marker at all = variety lost
                # A property the source has must not vanish on the way (told to reduce dialogue from 10% to
                # 4%, a model may remove all of it; the overall distance can still improve).
                lost = [k for k in keys if isinstance(target.get(k), (int, float)) and target[k] > 0
                        and (m.get(k) or 0) >= 0.3 * target[k] and (cm.get(k) or 0) < 0.3 * target[k]]
                # restoring the variety is worth a slightly larger style distance
                better_var = bool(vnote) and vs is not None and v0 is not None and vs >= v0 + 0.2 and cd <= d + 0.03
                kept = (cd < d or better_var) and change <= max_change and ok_lang and ok_var and not lost
                log["rounds"].append({"round": r, "gaps": gaps, "distance": cd, "length_change": round(change, 3),
                                      "language_ok": ok_lang, "variety_ok": ok_var, "lost": lost, "kept": kept})
                ctx.emit("conform_round", stage="conform", chapter=i, round=r, distance_before=round(d, 3),
                         distance=round(cd, 3), kept=kept, gaps=gaps, lost=lost, length_change=round(change, 3),
                         language_ok=ok_lang, variety_ok=ok_var)
                if not kept:
                    continue  # another attempt (sampling differs) while rounds remain
                text, m, d = cand, cm, cd
                if vs is not None:
                    v0 = vs
            if text != draft.text:
                draft.text, draft.word_count = text, word_count(text)
                ctx.store.write_json(path, draft)
            log.update(after={k: m.get(k) for k in keys}, distance_after=d)
            ctx.store.write_json(name, log)
            ctx.emit("stage_progress", stage="conform", chapter=i,
                     message=f"chapter {i}: style distance {d0:.2f} → {d:.2f}")

        await gather_limited(self._chapters(ctx), chapter, int(self.params.get("parallel_chapters", 4)))
