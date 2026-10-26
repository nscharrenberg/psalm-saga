"""Relating the synthetic text back to the story design (and through it to the source).

The source is analysed once (stage extract). The synthetic text is analysed once (stage recover).
Instead of comparing two independent analyses of two texts, the synthetic text's graph is aligned
with the *design* — the source's bible after renaming and the transform policy, which keeps the
source's ids. Design and text speak the same names (the writer was given the design), so most items
pair directly; what is left is related back in up to three model steps:

  1  rules     names, aliases and inflection-aware content words, in the synthetic name space
  2  entities  a model pairs the remaining characters, places, objects and organisations of the
               design with those the analysis found in the text, from their descriptions
  3  story     per chapter, a model pairs the remaining scenes and events, in story order, allowing
               one design scene to be told as two
  4  check     for design items still unmatched — events, characters, places, relations, causes —
               a model reads the synthetic chapter itself and says whether each is realised (yes /
               partly / no) with a short quotation as evidence: the analysis may simply have missed it

Because design ids are source ids, the alignment also says, for every source item, whether it was
kept, changed or lost — without re-extracting the source. The result is stored in
recovered/alignment.json and used by the evaluation (instrument KG), the graph comparison views and
the targeted fixes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from psalm_saga.artifacts import Bible
from psalm_saga.graph import STORY_TYPES, build_graph, compare_graphs
from psalm_saga.llm import Part

ROLE = ("You are a careful literary analyst relating two descriptions of the same story to each other. "
        "You pair items only on clear evidence.")


class Pair(BaseModel):
    a: str = Field(description="Id of the item in list A.")
    b: str = Field(description="Id of the item in list B that denotes the same thing.")
    confidence: Literal["high", "medium", "low"] = "medium"
    reason: str = Field("", description="Why they are the same, briefly.")


class Pairs(BaseModel):
    pairs: list[Pair] = Field(default_factory=list)


class Check(BaseModel):
    item: str = Field(description="The item's key, e.g. K3.")
    realised: Literal["yes", "partly", "no"]
    evidence: str = Field("", description="For yes or partly: a short quotation (at most 20 words) from the text.")


class Checks(BaseModel):
    items: list[Check] = Field(default_factory=list)


def _entity_line(n: dict) -> str:
    d = n.get("details") or {}
    al = ", ".join(d.get("aliases") or [])
    return (f"{n['id']} | {n['type']} | {n['label']}{f' (also: {al})' if al else ''} | chapters {','.join(map(str, n.get('chapters') or []))}"
            f" | {(d.get('description') or '')[:180]}")


def _story_line(n: dict) -> str:
    d = n.get("details") or {}
    who = ", ".join(d.get("characters") or [])
    return f"{n['id']} | {(d.get('summary') or d.get('description') or '')[:220]}{f' | with: {who}' if who else ''}"


async def align_to_design(ctx, design: Bible, text: Bible, chapter_texts: dict[int, str], *, use_model: bool = True,
                          check_text: bool = True, max_check: int = 40, role: str = "analysis") -> dict:
    dg, tg = build_graph(design), build_graph(text)
    dn = {n["id"]: n for n in dg["nodes"]}
    base = compare_graphs(dg, tg, {})
    pairs: list[dict] = [{"design": a, "text": b, "method": "rules"} for a, b in base["alignment"].items()]
    stats = {"rules": len(pairs), "model_entities": 0, "model_story": 0, "checked": 0, "found_by_check": 0}

    def taken() -> tuple[set[str], set[str]]:
        return {p["design"] for p in pairs}, {p["text"] for p in pairs}

    if use_model:
        # 2 — entities the rules could not pair
        da, ta = taken()
        left_d = [n for n in dg["nodes"] if n["type"] not in STORY_TYPES and n["id"] not in da]
        left_t = [n for n in tg["nodes"] if n["type"] not in STORY_TYPES and n["id"] not in ta]
        if left_d and left_t:
            prompt = ("List A is the design of a story: the characters, places, objects and organisations the writer was "
                      "asked to use. List B is what an analyst found when reading the story as written. Both use the same "
                      "names, but analysts word things differently: a title or role instead of a name (\"the mother\" for "
                      "a named mother), a nickname, singular for plural, a slightly different description, another "
                      "classification (a horse as a character or an object). Pair each A item with the B item that is "
                      "the same entity, if there is one. One-to-one; only when the descriptions agree; leave items "
                      "unpaired rather than guess.\n\n# List A (design)\n" + "\n".join(map(_entity_line, left_d[:90]))
                      + "\n\n# List B (found in the text)\n" + "\n".join(map(_entity_line, left_t[:90])))
            res = await ctx.json(role, ROLE, [Part(prompt)], Pairs, temperature=0.0,
                                 hints={"pairs": 0}, tag="recover:align:entities")
            ok_d, ok_t = {n["id"] for n in left_d}, {n["id"] for n in left_t}
            for p in res.pairs:
                if p.a in ok_d and p.b in ok_t and p.confidence != "low":
                    pairs.append({"design": p.a, "text": p.b, "method": "model", "confidence": p.confidence, "reason": p.reason})
                    ok_d.discard(p.a)
                    ok_t.discard(p.b)
                    stats["model_entities"] += 1
        # 3 — scenes and events, per chapter
        da, ta = taken()
        for ch in sorted({c for n in dg["nodes"] if n["type"] in ("scene", "event") for c in (n.get("chapters") or [])}):
            for typ in ("scene", "event"):
                sd = [n for n in dg["nodes"] if n["type"] == typ and ch in (n.get("chapters") or []) and n["id"] not in da]
                st = [n for n in tg["nodes"] if n["type"] == typ and ch in (n.get("chapters") or []) and n["id"] not in ta]
                if not sd or not st:
                    continue
                prompt = (f"Chapter {ch} of a story. List A gives the {typ}s the writer was asked to write (the design); "
                          f"list B the {typ}s an analyst found in the chapter as written, both in story order. Pair each A "
                          f"item with the B item that tells the same {typ}. Order is mostly kept. One A item may "
                          f"correspond to two consecutive B items when the text tells it in two parts: give both pairs. "
                          f"Pair only on clear agreement of what happens and who takes part.\n\n# List A (design)\n"
                          + "\n".join(map(_story_line, sd)) + "\n\n# List B (found in the text)\n" + "\n".join(map(_story_line, st)))
                res = await ctx.json(role, ROLE, [Part(prompt)], Pairs, temperature=0.0, hints={"pairs": 0},
                                     tag=f"recover:align:ch{ch}:{typ}")
                ok_d, ok_t = {n["id"] for n in sd}, {n["id"] for n in st}
                for p in res.pairs:
                    if p.a in ok_d and p.b in ok_t and p.confidence != "low":
                        pairs.append({"design": p.a, "text": p.b, "method": "model", "confidence": p.confidence,
                                      "reason": p.reason})
                        ok_t.discard(p.b)
                        stats["model_story"] += 1

    checks: dict[str, dict] = {}
    if use_model and check_text:
        # 4 — what is still unmatched: look in the text itself
        cmp = compare_graphs(dg, tg, {}, prealign=[(p["design"], p["text"]) for p in pairs])
        missing_nodes = [n for n in cmp["nodes"] if n["status"] == "source_only" and n["type"] != "chapter"]
        missing_edges = [e for e in cmp["edges"] if e["status"] == "source_only" and e["type"] in ("relation", "causes")]
        lab = lambda i: (dn.get(i) or {}).get("label", i)  # noqa: E731
        by_ch: dict[int, list[tuple[str, str]]] = {}
        for n in missing_nodes:
            d = n.get("details") or {}
            text_ = (f"[{n['type']}] {d.get('summary') or d.get('description') or ''}" if n["type"] in ("scene", "event")
                     else f"[{n['type']}] {n['label']} appears ({(d.get('description') or '')[:120]})")
            for ch in (n.get("chapters") or [])[:1]:  # an entity is checked in the first chapter it belongs to
                by_ch.setdefault(ch, []).append((n["id"], text_))
        for e in missing_edges:
            key = f"edge:{e['type']}:{e['source']}:{e['target']}"
            if e["type"] == "relation":
                text_ = f"[relation] {lab(e['source'])} — {e.get('label', '')} → {lab(e['target'])}"
            else:
                a = ((dn.get(e["source"]) or {}).get("details") or {}).get("description", "")
                b = ((dn.get(e["target"]) or {}).get("details") or {}).get("description", "")
                text_ = f"[cause] {a} — leads to — {b}"
            for ch in (e.get("chapters") or [])[:1]:
                by_ch.setdefault(ch, []).append((key, text_))
        for ch, items in sorted(by_ch.items()):
            body = chapter_texts.get(ch)
            if not body or not items:
                continue
            items = items[:max_check]
            keys = {f"K{i + 1}": k for i, (k, _) in enumerate(items)}
            prompt = ("Below is one chapter of a story, and a list of things the story's design says should be in it. "
                      "For each item, say whether the chapter realises it — yes, partly, or no — judging what happens, not "
                      "the exact wording (names are as in the chapter). For yes or partly, quote at most 20 words of the "
                      "chapter as evidence.\n\n# Items\n" + "\n".join(f"K{i + 1}. {t}" for i, (_, t) in enumerate(items))
                      + f"\n\n# Chapter\n{body}")
            res = await ctx.json(role, ROLE, [Part(prompt)], Checks, temperature=0.0, hints={"items": 0},
                                 tag=f"recover:check:ch{ch}")
            stats["checked"] += len(items)
            for c in res.items:
                k = keys.get(c.item.strip().upper())
                if k and c.realised in ("yes", "partly"):
                    checks[k] = {"realised": c.realised, "evidence": c.evidence[:240]}
                    stats["found_by_check"] += 1
    return {"pairs": pairs, "checks": checks, "stats": stats}


def _valid_for_source(source: Bible, design: Bible) -> callable:
    """Design ids are source ids for entities and scenes. Events can be re-told under an abstracting
    policy (a different number per chapter); their ids then do not correspond and are not carried over."""
    def per_chapter(b: Bible) -> dict[int, int]:
        return {c.index: len(c.events) for c in b.chapters}

    same_events = {ch for ch, n in per_chapter(source).items() if per_chapter(design).get(ch) == n}

    def ok(i: str) -> bool:
        if i.startswith("v"):
            try:
                return int(i[1:].split(".")[0]) in same_events
            except ValueError:
                return False
        return True
    return ok


def text_comparison(store, against: str = "source") -> dict | None:
    """The synthetic text's graph aligned with the design (`against="design"`) or, through the design's
    ids, with the source (`against="source"`), using recovered/alignment.json. None when the
    synthetic text has not been analysed or aligned yet."""
    from psalm_saga.artifacts import TransformMap

    rec = store.maybe("recovered/bible_source.json", Bible)
    design = store.maybe("bible.json", Bible)
    if rec is None or design is None or not store.exists("recovered/alignment.json"):
        return None
    al = store.read_json("recovered/alignment.json")
    pre = [(p["design"], p["text"]) for p in al.get("pairs", [])]
    checks = al.get("checks") or {}
    if against == "design":
        out = compare_graphs(build_graph(design), build_graph(rec), {}, prealign=pre, checks=checks)
    else:
        src = store.maybe("bible_source.json", Bible)
        if src is None:
            return None
        ok = _valid_for_source(src, design)
        tmap = store.maybe("transform.json", TransformMap)
        pre_s = [(a, b) for a, b in pre if ok(a)]
        checks_s = {k: v for k, v in checks.items()
                    if (ok(k) if not k.startswith("edge:") else all(ok(x) for x in k.split(":")[2:]))}
        out = compare_graphs(build_graph(src), build_graph(rec), tmap.as_dict() if tmap else {}, prealign=pre_s,
                             checks=checks_s)
    methods = {p["design"]: p.get("method", "rules") for p in al.get("pairs", [])}
    for n in out["nodes"]:
        if n["id"] in methods and n.get("status") in ("kept", "changed"):
            n.setdefault("details", {})["matched_by"] = {"rules": "names", "model": "model alignment"}.get(methods[n["id"]], methods[n["id"]])
    out["alignment_stats"] = al.get("stats") or {}
    return out
