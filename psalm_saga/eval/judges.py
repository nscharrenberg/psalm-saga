"""Model-judge instruments. All judges run at temperature 0 with a model that should be
disjoint from the generators (set `judge.model` in the experiment plan).

  spec_recovery      Extract a spec from the synthetic story with the same extractor used
                     on the source, then judge, per sub-dimension, whether the two specs
                     describe the same thing. Scales to novels: the judge sees two specs,
                     never two books. Answers "would a researcher extracting this data
                     point get the same answer from the synthetic text?"
  dimension_fidelity Direct pairwise read of source and synthetic excerpts, rating each
                     dimension's similarity 1-5. For short items / spot checks.
  quality_pairwise   Blind A/B preference between a condition and a baseline condition.
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field

from psalm_saga.artifacts import Spec
from psalm_saga.config import ModelConfig, PipelineConfig
from psalm_saga.llm import LLM, Part
from psalm_saga.taxonomy import Taxonomy

SYSTEM = ("You are an expert literary scholar acting as a blind, careful evaluator in a research study. "
          "Judge only what you are asked, on the evidence given.")


class SubJudgement(BaseModel):
    key: str
    verdict: Literal["same", "partial", "different"]
    reason: str = ""


class SpecComparison(BaseModel):
    items: list[SubJudgement]


class DimRating(BaseModel):
    dimension: str
    similarity: int = Field(ge=1, le=5, description="1 = unrelated, 5 = indistinguishable on this dimension")
    reason: str = ""


class DimRatings(BaseModel):
    ratings: list[DimRating]


class Preference(BaseModel):
    winner: Literal["A", "B", "tie"]
    reason: str = ""


def judge_llm(model: str, cache_dir=None, **model_kw) -> LLM:
    cfg = PipelineConfig(models={"default": ModelConfig(name=model, temperature=0.0, **model_kw)})
    return LLM(cfg, cache_dir=cache_dir)


async def spec_recovery(llm: LLM, taxonomy: Taxonomy, source_spec: Spec, synthetic_spec: Spec,
                        policies: dict[str, str]) -> dict:
    out: dict = {"by_dimension": {}, "by_subdimension": {}}
    for dim in taxonomy.dimensions:
        a, b = source_spec.dim(dim.key), synthetic_spec.dim(dim.key)
        if not a or not b:
            continue
        pol = policies.get(dim.key, "preserve")
        level = ("the concrete realisation" if pol == "preserve" else
                 "function and structure only — concrete particulars (names, places, objects, specific traits) are SUPPOSED to differ")
        prompt = (
            f"Two analysts independently described the dimension '{dim.label}' of two texts. Names differ by design; "
            f"ignore them. Compare at the level of {level}. For each sub-dimension, answer same / partial / different.\n\n"
            f"# Description 1\n{Spec(language='', target_words=0, chapters=0, dimensions=[a]).render()}\n\n"
            f"# Description 2\n{Spec(language='', target_words=0, chapters=0, dimensions=[b]).render()}\n\n"
            f"Sub-dimension keys: {', '.join(s.key for s in dim.subdimensions)}")
        res = await llm.json("judge", SYSTEM, [Part(prompt)], SpecComparison, temperature=0.0,
                             hints={"items": len(dim.subdimensions)}, tag=f"judge:spec_recovery:{dim.key}")
        score = {"same": 1.0, "partial": 0.5, "different": 0.0}
        vals = []
        for j in res.items:
            out["by_subdimension"][f"{dim.key}.{j.key}"] = j.verdict
            vals.append(score[j.verdict])
        out["by_dimension"][dim.key] = {"policy": pol, "score": round(sum(vals) / len(vals), 3) if vals else None}
    scores = [v["score"] for v in out["by_dimension"].values() if v["score"] is not None]
    out["mean"] = round(sum(scores) / len(scores), 3) if scores else None
    return out


def _excerpt(text: str, words: int) -> str:
    toks = text.split()
    return " ".join(toks[:words]) + (" […]" if len(toks) > words else "")


async def dimension_fidelity(llm: LLM, taxonomy: Taxonomy, source: str, synthetic: str, *, words: int = 3500) -> dict:
    dims = "\n".join(f"- {d.key}: {d.label} — {d.description}" for d in taxonomy.dimensions)
    prompt = (f"Text 2 was derived from Text 1 with new names and particulars. Rate, for each dimension, how similar the two "
              f"texts are (1-5), ignoring names.\n\nDimensions:\n{dims}\n\n# Text 1\n{_excerpt(source, words)}\n\n"
              f"# Text 2\n{_excerpt(synthetic, words)}")
    res = await llm.json("judge", SYSTEM, [Part(prompt)], DimRatings, temperature=0.0,
                         hints={"ratings": len(taxonomy.dimensions)}, tag="judge:dimension_fidelity")
    return {r.dimension: r.similarity for r in res.ratings}


async def quality_pairwise(llm: LLM, a_text: str, b_text: str, *, seed: str, words: int = 3000) -> dict:
    """Returns {'winner': 'condition'|'baseline'|'tie'} with presentation order randomised by seed."""
    flip = random.Random(seed).random() < 0.5
    first, second = (b_text, a_text) if flip else (a_text, b_text)
    prompt = ("Which story is better written as literary fiction — prose quality, coherence, characterisation, and how "
              "engaging it is to read? Ignore length differences.\n\n"
              f"# Story A\n{_excerpt(first, words)}\n\n# Story B\n{_excerpt(second, words)}")
    res = await llm.json("judge", SYSTEM, [Part(prompt)], Preference, temperature=0.0, tag="judge:quality")
    if res.winner == "tie":
        return {"winner": "tie", "reason": res.reason}
    cond_won = (res.winner == "A") != flip
    return {"winner": "condition" if cond_won else "baseline", "reason": res.reason}


# ------------------------------------------------------------------ added instruments
#
#   emotional_arc   F8  valence of k evenly spaced passages, rated separately for T and S;
#                       Pearson r between the two arcs (Reagan et al. 2016 for arcs as a
#                       research object; Zhang et al. 2024 for LLM sentiment rating)
#   surface_reuse   D3  non-literal reuse: concrete particulars and close paraphrases of T
#                       that survive in S, on aligned chapter pairs (CopyBench's non-literal
#                       copying, Chen et al. 2024; idea/expression line of Henderson et al. 2023)
#   reconstruction  D5  an attacker who sees only S tries to name the work and rewrite the
#                       original wording; scored deterministically against T


class Valence(BaseModel):
    passage: int
    valence: int = Field(ge=-5, le=5, description="-5 very negative ... 0 neutral ... +5 very positive")


class Valences(BaseModel):
    ratings: list[Valence]


class ReuseItem(BaseModel):
    kind: Literal["close_paraphrase", "distinctive_particular"]
    evidence: str = Field(description="A few words from Text B (at most 12).")
    note: str = ""


class ReuseReport(BaseModel):
    items: list[ReuseItem] = Field(default_factory=list)


class Reconstruction(BaseModel):
    title_guess: str = ""
    author_guess: str = ""
    confidence: int = Field(0, ge=0, le=100)
    original_passage: str = Field("", description="The passage as it appears in the original work, as exactly as you can.")


def segments(text: str, k: int, words: int) -> list[str]:
    toks = text.split()
    if not toks:
        return []
    k = max(1, min(k, len(toks) // max(words, 1) or 1))
    seg = len(toks) / k
    out = []
    for i in range(k):
        mid = int(seg * (i + 0.5))
        lo = max(0, mid - words // 2)
        out.append(" ".join(toks[lo : lo + words]))
    return out


async def _arc(llm: LLM, text: str, k: int, words: int, tag: str) -> list[float]:
    parts = segments(text, k, words)
    listing = "\n\n".join(f"[Passage {i + 1}]\n{p}" for i, p in enumerate(parts))
    prompt = ("Rate the emotional valence of each passage of this story, as experienced in the story world at that point "
              "(-5 very negative, 0 neutral, +5 very positive). Rate each passage on its own.\n\n" + listing)
    res = await llm.json("judge", SYSTEM, [Part(prompt)], Valences, temperature=0.0, hints={"ratings": len(parts)}, tag=tag)
    by = {r.passage: float(r.valence) for r in res.ratings}
    return [by.get(i + 1, 0.0) for i in range(len(parts))]


async def emotional_arc(llm: LLM, source: str, synthetic: str, *, k: int = 10, words: int = 350) -> dict:
    from psalm_saga.text.metrics import pearson

    a = await _arc(llm, source, k, words, "judge:arc:source")
    b = await _arc(llm, synthetic, k, words, "judge:arc:synthetic")
    n = min(len(a), len(b))
    r = pearson(a[:n], b[:n])
    return {"source": a, "synthetic": b, "pearson": None if r is None else round(r, 3),
            "mean_abs_diff": round(sum(abs(x - y) for x, y in zip(a, b, strict=False)) / n, 3) if n else None}


async def surface_reuse(llm: LLM, source_chapters: list[str], synthetic_chapters: list[str], policies: dict[str, str],
                        *, samples: int = 3, words: int = 1200) -> dict:
    n = min(len(source_chapters), len(synthetic_chapters))
    if not n:
        return {"pairs": 0}
    idx = sorted({round(i * (n - 1) / max(samples - 1, 1)) for i in range(min(samples, n))})
    changed = [k for k, v in policies.items() if v != "preserve"] or ["(none: only names and wording change)"]
    counts = {"close_paraphrase": 0, "distinctive_particular": 0}
    syn_words = 0
    examples = []
    for i in idx:
        a, b = _excerpt(source_chapters[i], words), _excerpt(synthetic_chapters[i], words)
        syn_words += len(b.split())
        prompt = (
            "Text B was written from a structural description of Text A, without access to A's wording. The plot events, "
            "relationships and narrative roles are meant to correspond, and are NOT reuse. List only what in B is "
            "recognisably taken from A's surface: (a) close_paraphrase — a sentence or line of dialogue in B that follows a "
            "specific sentence in A closely in wording or image; (b) distinctive_particular — a concrete detail (an unusual "
            f"object, image, mannerism, place detail) carried over although these dimensions were meant to change: {', '.join(changed)}. "
            "An empty list is a normal answer.\n\n"
            f"# Text A\n{a}\n\n# Text B\n{b}")
        res = await llm.json("judge", SYSTEM, [Part(prompt)], ReuseReport, temperature=0.0, hints={"items": 0},
                             tag=f"judge:surface_reuse:{i + 1}")
        for it in res.items:
            counts[it.kind] += 1
            if len(examples) < 10:
                examples.append({"chapter": i + 1, "kind": it.kind, "evidence": it.evidence[:120]})
    per_1k = round(1000 * sum(counts.values()) / max(syn_words, 1), 3)
    return {"pairs": len(idx), "synthetic_words_read": syn_words, **counts, "per_1k": per_1k, "examples": examples}


def _norm_title(s: str) -> set[str]:
    import re

    return {w for w in re.findall(r"\w+", s.lower()) if len(w) > 2 and w not in {"the", "het", "een", "and", "van", "der", "de"}}


async def reconstruction(llm: LLM, source: str, synthetic: str, *, words: int = 400, positions: tuple[float, ...] = (0.0, 0.5),
                         title: str | None = None, author: str | None = None) -> dict:
    from psalm_saga.text.metrics import SourceIndex, ngram_overlap

    toks = synthetic.split()
    index = SourceIndex(source, n=5)
    trials = []
    for pos in positions:
        lo = int(len(toks) * pos)
        excerpt = " ".join(toks[lo : lo + words])
        if not excerpt:
            continue
        prompt = ("The passage below is a disguised rewrite of a passage from a published literary work: names, places "
                  "and wording were changed. Identify the work if you can, and write the original passage as exactly as "
                  "you can, in its original language. If you do not know the work, say so and leave the passage empty.\n\n"
                  f"{excerpt}")
        res = await llm.json("judge", SYSTEM, [Part(prompt)], Reconstruction, temperature=0.0, tag=f"judge:reconstruction:{pos}")
        rec = res.original_passage or ""
        spans = index.spans(rec, min_len=8) if rec else []
        trials.append({
            "position": pos,
            "confidence": res.confidence,
            "title_guess": res.title_guess, "author_guess": res.author_guess,
            # Overlap of the attacker's text with T, against the overlap S itself already has.
            "ngram5_reconstruction": round(ngram_overlap(source, rec, 5), 4) if rec else 0.0,
            "ngram5_synthetic": round(ngram_overlap(source, excerpt, 5), 4),
            "longest_span_reconstruction": spans[0]["length"] if spans else 0,
        })
    out: dict = {"trials": trials}
    if trials:
        out["ngram5_gain"] = round(sum(t["ngram5_reconstruction"] - t["ngram5_synthetic"] for t in trials) / len(trials), 4)
        out["longest_span"] = max(t["longest_span_reconstruction"] for t in trials)
    if title:
        want = _norm_title(title)
        hits = [bool(want) and len(want & _norm_title(t["title_guess"])) / len(want) >= 0.5 for t in trials]
        out["identified"] = any(hits)
    if author:
        want = _norm_title(author)
        out["author_identified"] = any(bool(want & _norm_title(t["author_guess"])) for t in trials)
    return out
