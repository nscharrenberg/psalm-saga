"""conform: bring each drafted chapter's rhythm onto the source's measured targets.

Drafting prompts state the targets, but models drift back to their own register (short
sentences, one-line paragraphs, invented dialogue). This stage measures every chapter
deterministically and, when it is off target, asks for a *layout and rhythm* revision with the
measured numbers and concrete operations (join sentences, merge paragraphs, report speech): the
same events, details, names, language and variety. A revision is kept only if it moves the
chapter closer to the targets without changing its length by more than `max_length_change`
or losing language-variety forms; a rejected attempt is retried while `rounds` remain
(default 2). Rounds stop early when they stop paying off: after `patience` (default 2) rejected
attempts in a row, or after a kept revision that gained less than `min_gain` (default 0.005). Each
round rewrites the whole chapter, so with a tight tolerance the rounds would otherwise all be spent.

What is steered: the features in text/style.py (TARGET_KEYS: sentence and paragraph length,
dialogue shares, punctuation rates) and the sentence- and paragraph-length *distributions*
(Kolmogorov–Smirnov gap to the source's, from the profile's numbers). Each quantity has a weight;
measures the run prioritises weigh more (psalm_saga/priorities.py). The function-word profile and
character n-grams are not steered, so evaluation keeps independent evidence of style; the
ablation `stages.conform.enabled=false` measures what the stage contributes. Only numbers from
the source profile are used, so the clean-room boundary holds.

`conform_text` is also used by review: a chapter that review redrafts from a revised plan is
conformed again before it is accepted, so content repairs never throw the style work away.
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
    ks,
    layout_reliable,
    length_distributions,
    measure,
    paragraph_gap,
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


class Objective:
    """What conform minimises for one run: a weighted mean of the relative differences of the steered
    features and of the KS gaps of the sentence- and paragraph-length distributions."""

    def __init__(self, ctx: RunContext):
        from psalm_saga.priorities import weight

        targets = ctx.style_targets or {}
        self.language = ctx.language
        self.fp = targets.get("form") or {"form": "prose"}
        self.form = self.fp.get("form", "prose")
        self.verse = self.form == "verse"
        stylo = targets.get("stylometrics") or {}
        self.target = verse_target(stylo, self.fp) if self.verse else stylo
        self.keys = VERSE_KEYS if self.verse else target_keys(self.target)
        self.shape = targets.get("shape") or {}
        self.src_sent, self.src_par = ([], []) if self.verse else length_distributions(self.shape)
        if not layout_reliable(stylo):
            self.src_par = []
        pr = ctx.config.priorities
        w_feat = weight(pr, "style_drift")
        self.weights = {k: w_feat for k in self.keys}
        if self.src_sent:
            self.weights["sentence_distribution"] = weight(pr, "sentence_overlap")
        if self.src_par and len(self.src_par) >= 8:
            self.weights["paragraph_distribution"] = weight(pr, "paragraph_overlap")
        # The frequent-word profile is independent evidence of style and is not steered by default;
        # a study that prioritises it (fw_cosine) has it steered too.
        self.src_fw = targets.get("function_words") or {}
        if self.src_fw and not self.verse and weight(pr, "fw_cosine") > 1:
            self.weights["function_words"] = weight(pr, "fw_cosine")
        if not self.verse:
            for k in ("mean_paragraph_words", "dialogue_paragraph_share"):
                if k in self.weights:
                    self.weights[k] = max(self.weights[k], weight(pr, "paragraph_overlap"))
            for k in ("mean_sentence_words", "sd_sentence_words"):
                self.weights[k] = max(self.weights.get(k, 1.0), weight(pr, "sentence_overlap"))

    def parts(self, text: str) -> tuple[dict, dict]:
        """(measured features, per-quantity difference 0–1)."""
        m = measure(text, self.language, self.form)
        d: dict[str, float] = {}
        for k in self.keys:
            a, b = float(m.get(k) or 0), float(self.target.get(k) or 0)
            if a == b:
                d[k] = 0.0
            elif k.endswith("_share") and max(a, b) < 0.08:
                d[k] = min(1.0, abs(a - b) / 0.08)
            else:
                d[k] = abs(a - b) / max(abs(a), abs(b))
        if "sentence_distribution" in self.weights or "paragraph_distribution" in self.weights:
            sent, par = length_distributions(shape(text))
            if "sentence_distribution" in self.weights:
                d["sentence_distribution"] = ks(self.src_sent, sent) or 0.0
            if "paragraph_distribution" in self.weights:
                d["paragraph_distribution"] = ks(self.src_par, par) or 0.0 if len(par) >= 3 else 0.0
        if "function_words" in self.weights:
            from psalm_saga.text.style import word_rate_gaps

            d["function_words"] = min(1.0, 4 * word_rate_gaps(self.src_fw, text)[0])  # a cosine gap of 0.25 counts as fully off
        return m, d

    def score(self, text: str) -> tuple[float, dict, dict]:
        m, d = self.parts(text)
        tot = sum(self.weights.get(k, 1.0) for k in d) or 1.0
        dist = sum(self.weights.get(k, 1.0) * v for k, v in d.items()) / tot
        if self.verse and m.get("form") != "verse":
            dist += 0.5
        return round(dist, 4), m, d

    def gaps(self, text: str, m: dict, d: dict) -> list[str]:
        if self.verse:
            return verse_gaps(m, self.target, self.fp)
        out = style_gaps(m, self.target, shp_target=self.shape, shp_measured=shape(text))
        pd = d.get("paragraph_distribution")
        if pd is not None and pd > 0.15:
            _, par = length_distributions(shape(text))
            g = paragraph_gap(self.src_par, par, pd)
            if g:
                out.append(g)
        fw = d.get("function_words")
        if fw is not None and fw > 0.2:
            from psalm_saga.text.style import word_rate_gaps

            _, worst = word_rate_gaps(self.src_fw, text, 8)
            out.append("The most frequent words are used at different rates from the source (per 1,000 words, source → "
                       "here): " + "; ".join(f"“{w}” {a:g} → {b:g}" for w, a, b in worst)
                       + ". Shift the habits toward the source's — e.g. how clauses are joined (and, but, so), articles, "
                         "pronouns, verb forms — without forcing words where they do not fit.")
        sd = d.get("sentence_distribution")
        if sd is not None and sd > 0.15 and not any("Sentence lengths" in x for x in out):
            sq = self.shape.get("sentence_quantiles") or []
            if len(sq) == 5:
                out.append(f"The spread of sentence lengths differs from the source's (gap {sd:.2f}): in the source a "
                           f"quarter of the sentences are shorter than {sq[1]:.0f} words, half shorter than {sq[2]:.0f}, "
                           f"and one in ten longer than {sq[4]:.0f}. Reshape sentences to that spread.")
        return out


def style_distance(ctx: RunContext, text: str) -> float | None:
    """Distance of a text from the source's measured style (the number conform minimises), or None
    when there are no style targets (no source) or the form has none (drama)."""
    targets = ctx.style_targets or {}
    if not targets or (targets.get("form") or {}).get("form") == "drama":
        return None
    return Objective(ctx).score(text)[0]


async def conform_text(ctx: RunContext, stage: Stage, text: str, index: int, n_ch: int, *, tag: str = "conform",
                       reference_words: int | None = None) -> tuple[str, dict]:
    """Revise one chapter's rhythm and layout toward the source's measured targets.
    Returns (text, log). The text is unchanged when it is already within tolerance."""
    params = stage.params
    obj = Objective(ctx)
    tol = float(params.get("tolerance", 0.12))
    rounds = int(params.get("rounds", 2))
    max_change = float(params.get("max_length_change", 0.12))
    patience = max(1, int(params.get("patience", 2)))
    min_gain = float(params.get("min_gain", 0.005))
    piece_words = int(params.get("passage_words", 1800))
    variety = ctx.variety
    span = 1 / max(n_ch, 1)
    position = (index - 1) / max(n_ch, 1)
    ref_words = reference_words or word_count(text)

    async def revise(cur: str, measured: dict, gaps: list[str], attempt: int, r: int) -> str:
        pieces = passages(cur, piece_words)
        offsets, acc = [], 0
        for pc in pieces:
            offsets.append(acc / max(word_count(cur), 1))
            acc += word_count(pc)

        async def one(args) -> str:
            k, piece = args
            scaffold = "" if obj.verse else rhythm_scaffold(obj.shape, word_count(piece), position + offsets[k] * span)
            prompt = ctx.prompts.render("conform_verse" if obj.verse else "conform",
                                        table=_table(measured, obj.target, obj.keys), gaps=gaps, text=piece,
                                        scaffold=scaffold, words=word_count(piece),
                                        language=language_name(ctx.language), variety=variety)
            return clean_prose(await ctx.text(stage.model_role, ROLE, [Part(prompt)],
                                              max_tokens=int(word_count(piece) * 2.4) + 400,
                                              hints=ctx.hints(target_words=word_count(piece), variant=attempt),
                                              tag=f"{tag}:ch{index}r{r}"))

        out = await gather_limited(list(enumerate(pieces)), one, int(params.get("parallel", 4)))
        return "\n\n".join(o for o in out if o.strip())

    d, m, parts = obj.score(text)
    d0 = d
    log = {"index": index, "form": obj.form, "tolerance": tol, "weights": obj.weights,
           "before": {k: m.get(k) for k in obj.keys}, "parts_before": parts, "distance_before": d0, "rounds": []}
    v0 = (variety_share(text, variety, min_hits=3) or {}).get("share") if variety else None
    misses = 0
    for r in range(1, rounds + 1):
        vnote = variety_gap(text, variety)
        if (d <= tol and not vnote) or word_count(text) < 80:
            break
        gaps = obj.gaps(text, m, parts)
        if vnote:
            gaps = [*gaps, vnote]
        if not gaps:
            break
        cand = await revise(text, m, gaps, r, r)  # variant: a new sample per attempt
        cd, cm, cparts = obj.score(cand)
        change = abs(word_count(cand) - ref_words) / max(ref_words, 1)
        ok_lang = word_count(cand) < 120 or detect_language(cand).code == ctx.language
        ok_var, vs = True, None
        if variety and v0 is not None:
            vs = (variety_share(cand, variety, min_hits=3) or {}).get("share")
            ok_var = vs is not None and vs >= v0 - 0.1  # no marker at all = variety lost
        # A property the source has must not vanish on the way (told to reduce dialogue from 10% to
        # 4%, a model may remove all of it; the overall distance can still improve).
        lost = [k for k in obj.keys if isinstance(obj.target.get(k), (int, float)) and obj.target[k] > 0
                and (m.get(k) or 0) >= 0.3 * obj.target[k] and (cm.get(k) or 0) < 0.3 * obj.target[k]]
        # A prioritised quantity must not get clearly worse, even if the total improves.
        hurt = [k for k, w in obj.weights.items() if w > 1 and cparts.get(k, 0) > parts.get(k, 0) + 0.05]
        better_var = bool(vnote) and vs is not None and v0 is not None and vs >= v0 + 0.2 and cd <= d + 0.03
        kept = (cd < d or better_var) and change <= max_change and ok_lang and ok_var and not lost and not hurt
        log["rounds"].append({"round": r, "gaps": gaps, "distance": cd, "parts": cparts, "length_change": round(change, 3),
                              "language_ok": ok_lang, "variety_ok": ok_var, "lost": lost, "hurt": hurt, "kept": kept})
        ctx.emit("conform_round", stage=stage.name, chapter=index, round=r, distance_before=round(d, 3),
                 distance=round(cd, 3), kept=kept, gaps=gaps, lost=lost, hurt=hurt, length_change=round(change, 3),
                 language_ok=ok_lang, variety_ok=ok_var, context=tag)
        if not kept:
            misses += 1
            if misses >= patience:
                log["stopped"] = f"{misses} attempts in a row did not improve the chapter"
                break
            continue  # another attempt (sampling differs) while rounds remain
        misses, gain = 0, d - cd
        text, m, d, parts = cand, cm, cd, cparts
        if vs is not None:
            v0 = vs
        if gain < min_gain and not better_var:
            log["stopped"] = f"the last revision gained only {gain:.3f}"
            break
    log.update(after={k: m.get(k) for k in obj.keys}, parts_after=parts, distance_after=d)
    return text, log


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
        form = ((ctx.style_targets or {}).get("form") or {}).get("form", "prose")
        if form == "drama":  # speaker-labelled text: layout operations would break the format
            for i in self._chapters(ctx):
                ctx.store.write_json(f"conform/ch_{i:03d}.json", {"index": i, "skipped": "drama"})
            return
        n_ch = max(len(self._chapters(ctx)), 1)

        async def chapter(i: int):
            name = f"conform/ch_{i:03d}.json"
            if ctx.store.exists(name):
                return
            path = f"chapters/ch_{i:03d}.json"
            draft = ctx.store.read_json(path, ChapterDraft)
            text, log = await conform_text(ctx, self, draft.text, i, n_ch)
            if text != draft.text:
                draft.text, draft.word_count = text, word_count(text)
                ctx.store.write_json(path, draft)
            ctx.store.write_json(name, log)
            ctx.emit("stage_progress", stage="conform", chapter=i,
                     message=f"chapter {i}: style distance {log['distance_before']:.2f} → {log['distance_after']:.2f}")

        await gather_limited(self._chapters(ctx), chapter, int(self.params.get("parallel_chapters", 4)))
