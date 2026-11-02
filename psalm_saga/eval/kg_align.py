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
    is_story = lambda i: (dn.get(i) or {}).get("type") in ("scene", "event")  # noqa: E731
    # Entities by rules first. Scenes and events: word overlap in story order can pair a whole
    # chapter one step out of line when the two analyses cut the story differently, so with a model
    # available the model pairs them (all of them, per chapter) and the rules only fill in where
    # the model gave no answer for a chapter.
    pairs: list[dict] = [{"design": a, "text": b, "method": "rules"} for a, b in base["alignment"].items()
                         if not (use_model and is_story(a))]
    story_rules = [(a, b) for a, b in base["alignment"].items() if use_model and is_story(a)]
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
        answered: set[tuple[int, str]] = set()
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
                        answered.add((ch, typ))
        # rules for the chapters the model did not answer
        da, ta = taken()
        for a, b in story_rules:
            n = dn.get(a) or {}
            if a in da or b in ta or ((n.get("chapters") or [0])[0], n.get("type")) in answered:
                continue
            pairs.append({"design": a, "text": b, "method": "rules"})
            da.add(a)
            ta.add(b)
            stats["rules"] += 1

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


# Which dimension owns each kind of graph item (for reading source-side comparisons under a policy).
DIM_OF = {"character": "character", "place": "world_building", "object": "world_building", "organisation": "world_building",
          "other": "world_building", "scene": "scene_sequence", "event": "plot_structure",
          "relation:social": "character", "relation:world": "world_building", "causes": "plot_structure"}


def mark_policy(cmp: dict, policy: dict | None) -> dict:
    """In a comparison in source coordinates, an item the design re-invented or replaced on purpose is
    not 'kept' even when it is paired by identity: mark it changed, with the policy as the reason."""
    if not policy:
        return cmp
    word = {"abstract": "re-invented", "regenerate": "replaced"}
    for n in cmp.get("nodes", []):
        p = policy.get(DIM_OF.get(n["type"], ""), "preserve")
        if n.get("status") == "kept" and p in word:
            n["status"] = "changed"
            n["diff"] = "; ".join(x for x in (f"{word[p]} by the policy", n.get("diff", "")) if x)
            n.setdefault("details", {})["by_policy"] = p
    for e in cmp.get("edges", []):
        key = "causes" if e["type"] == "causes" else f"relation:{e.get('group', '')}" if e["type"] == "relation" else ""
        p = policy.get(DIM_OF.get(key, ""), "preserve")
        if e.get("status") == "kept" and p in word:
            e["status"] = "changed"
            e["diff"] = "; ".join(x for x in (f"{word[p]} by the policy", e.get("diff", "")) if x)
    return cmp


def _policy(store) -> dict:
    return ((store.meta().get("config") or {}).get("transform") or {}).get("policy") or {}


def _valid_for_source(source: Bible, design: Bible, new_story: bool = False) -> callable:
    """Design ids are source ids for entities and scenes. Events can be re-told under an abstracting
    policy (a different number per chapter); their ids then do not correspond and are not carried over.
    When the policy replaced the story (a new skeleton), no scene or event corresponds to the source's."""
    def per_chapter(b: Bible) -> dict[int, int]:
        return {c.index: len(c.events) for c in b.chapters}

    same_events = {ch for ch, n in per_chapter(source).items() if per_chapter(design).get(ch) == n}

    def ok(i: str) -> bool:
        if new_story and (i.startswith("v") or i.startswith("s")):
            return False
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
        log = store.read_json("transform_log.json") if store.exists("transform_log.json") else {}
        ok = _valid_for_source(src, design, log.get("skeleton") == "new story")
        tmap = store.maybe("transform.json", TransformMap)
        pre_s = [(a, b) for a, b in pre if ok(a)]
        checks_s = {k: v for k, v in checks.items()
                    if (ok(k) if not k.startswith("edge:") else all(ok(x) for x in k.split(":")[2:]))}
        out = mark_policy(compare_graphs(build_graph(src), build_graph(rec), tmap.as_dict() if tmap else {}, prealign=pre_s,
                                         checks=checks_s), _policy(store))
    methods = {p["design"]: p.get("method", "rules") for p in al.get("pairs", [])}
    for n in out["nodes"]:
        if n["id"] in methods and n.get("status") in ("kept", "changed"):
            n.setdefault("details", {})["matched_by"] = {"rules": "names", "model": "model alignment"}.get(methods[n["id"]], methods[n["id"]])
    out["alignment_stats"] = al.get("stats") or {}
    return out


# ------------------------------------------------------------------ trace: where did a difference arise?

VERDICTS = {
    "kept": "kept throughout",
    "policy": "changed by the design (the policy)",
    "dropped": "left out by the design",
    "written_changed": "changed in the writing",
    "written_lost": "lost in the writing",
    "design_added": "added by the design",
    "written_added": "added in the writing",
}
_TRACE_EDGES = ("relation", "causes")


def trace(store) -> dict | None:
    """Follow every source item through the design to the synthetic text, and say where a
    difference arose: in the design (the transform policy — intended) or in the writing (the
    generation — a loss or drift). One row per entity, scene, event, relation and causal link:
    {kind, type, id, source, design, text, design_status, text_status, verdict, note, evidence}.
    None when the synthetic text has not been analysed and aligned yet."""
    from psalm_saga.artifacts import TransformMap

    src = store.maybe("bible_source.json", Bible)
    design = store.maybe("bible.json", Bible)
    if src is None or design is None:
        return None
    tmap = store.maybe("transform.json", TransformMap)
    c1 = mark_policy(compare_graphs(build_graph(src), build_graph(design), tmap.as_dict() if tmap else {}), _policy(store))
    c2 = text_comparison(store, "design")
    if c2 is None:
        return None
    a1 = c1.get("alignment") or {}
    n2 = {n["id"]: n for n in c2["nodes"]}
    dg = {n["id"]: n for n in build_graph(design)["nodes"]}
    tg = {n["id"]: n for n in build_graph(store.maybe("recovered/bible_source.json", Bible) or Bible())["nodes"]}
    a2 = c2.get("alignment") or {}

    def ek(e: dict, a: str, b: str) -> tuple:
        if e["type"] == "relation":
            return (e["type"], a, b)
        return (e["type"], a, b)

    e2 = {ek(e, e["source"], e["target"]): e for e in c2["edges"] if e["type"] in _TRACE_EDGES}

    def text_side(i: str | None) -> tuple[str, dict | None]:
        if i is None:
            return "", None
        n = n2.get(i)
        return ((n or {}).get("status") or "source_only"), n

    def verdict(ds: str, ts: str) -> str:
        if ds == "source_only":
            return "dropped"
        if ds == "synthetic_only":
            return "design_added" if ts in ("kept", "changed") else "written_lost"
        if ts == "source_only":
            return "written_lost"
        if ds == "changed":
            return "policy"
        return "written_changed" if ts == "changed" else "kept"

    def label(n: dict | None) -> str:
        if not n:
            return ""
        d = n.get("details") or {}
        return (d.get("summary") or d.get("description") or n.get("label") or "")[:240] if n["type"] in ("scene", "event") \
            else n.get("label", "")

    def dlabel(i: str | None) -> str:
        return label(dg.get(i)) if i else ""

    def tlabel(i: str | None) -> str:
        """The synthetic text's own wording of the design item `i` (its analysis' label or summary)."""
        if not i:
            return ""
        t = a2.get(i)
        if t and t in tg:
            return label(tg[t])
        n = n2.get(i)
        if n and (n.get("details") or {}).get("checked"):
            return "“" + n["details"]["checked"].get("evidence", "") + "” (found by checking the text)"
        return label(n)

    rows: list[dict] = []
    for n in c1["nodes"]:
        if n["type"] == "chapter":
            continue
        ds = n["status"]
        if ds == "synthetic_only":
            did = n["id"][2:] if n["id"].startswith("y:") else n["id"]
            ts, tn = text_side(did)
            rows.append({"kind": "node", "type": n["type"], "id": did, "source": "", "design": dlabel(did) or label(n),
                         "text": tlabel(did) if ts in ("kept", "changed") else "", "design_status": ds, "text_status": ts,
                         "verdict": verdict(ds, ts), "note": (tn or {}).get("diff", ""),
                         "evidence": ((tn or {}).get("details") or {}).get("checked", {}).get("evidence", ""),
                         "matched_by": ((tn or {}).get("details") or {}).get("matched_by", ""), "chapters": n.get("chapters")})
            continue
        did = a1.get(n["id"]) if ds != "source_only" else None
        ts, tn = text_side(did)
        rows.append({"kind": "node", "type": n["type"], "id": n["id"], "source": label(n),
                     "design": dlabel(did) if ds != "source_only" else "",
                     "text": tlabel(did) if ts in ("kept", "changed") else "",
                     "design_status": ds, "text_status": ts or "", "verdict": verdict(ds, ts),
                     "note": "; ".join(x for x in (n.get("diff") if ds == "changed" else "", (tn or {}).get("diff", "")) if x),
                     "evidence": ((tn or {}).get("details") or {}).get("checked", {}).get("evidence", ""),
                     "matched_by": ((tn or {}).get("details") or {}).get("matched_by", ""), "chapters": n.get("chapters")})
    # Items the writer added that the design did not have.
    for n in c2["nodes"]:
        if n["status"] == "synthetic_only" and n["type"] != "chapter":
            rows.append({"kind": "node", "type": n["type"], "id": n["id"], "source": "", "design": "", "text": label(n),
                         "design_status": "", "text_status": "synthetic_only", "verdict": "written_added", "note": "",
                         "evidence": "", "matched_by": "", "chapters": n.get("chapters")})
    lab1 = {n["id"]: n.get("label", "") for n in c1["nodes"]}
    for e in c1["edges"]:
        if e["type"] not in _TRACE_EDGES:
            continue
        ds = e["status"]
        a, b = e["source"], e["target"]
        name = (f"{lab1.get(a, a)} — {e.get('label', '')} → {lab1.get(b, b)}" if e["type"] == "relation"
                else f"{label(next((x for x in c1['nodes'] if x['id'] == a), None))[:90]} → leads to → "
                     f"{label(next((x for x in c1['nodes'] if x['id'] == b), None))[:90]}")
        if ds == "synthetic_only":
            continue  # links the design added are rare and follow from added items above
        da, db = a1.get(a), a1.get(b)
        te = e2.get(ek(e, da, db)) if ds != "source_only" and da and db else None
        if te is None and e["type"] == "relation" and da and db:
            te = e2.get(ek(e, db, da))
        ts = (te or {}).get("status", "source_only") if ds != "source_only" else ""
        dname = (f"{dlabel(da)} — {e.get('label', '')} → {dlabel(db)}" if e["type"] == "relation"
                 else f"{dlabel(da)[:90]} → leads to → {dlabel(db)[:90]}") if da and db else ""
        tname = ""
        if ts in ("kept", "changed") and da and db:
            tname = (f"{tlabel(da)} — {(te or {}).get('label') or e.get('label', '')} → {tlabel(db)}" if e["type"] == "relation"
                     else f"{tlabel(da)[:90]} → leads to → {tlabel(db)[:90]}")
        rows.append({"kind": "edge", "type": e["type"] if e["type"] == "causes" else f"relation:{e.get('group', '')}".rstrip(":"),
                     "id": f"{e['type']}:{a}:{b}", "source": name, "design": dname if ds != "source_only" else "",
                     "text": tname, "design_status": ds, "text_status": ts,
                     "verdict": verdict(ds, ts), "note": "; ".join(x for x in (e.get("diff") if ds == "changed" else "",
                                                                                (te or {}).get("diff", "")) if x),
                     "evidence": "", "matched_by": "", "chapters": e.get("chapters")})
    summary: dict[str, dict[str, int]] = {}
    for r in rows:
        summary.setdefault(r["type"], dict.fromkeys(VERDICTS, 0))[r["verdict"]] += 1
    return {"rows": rows, "summary": summary, "verdicts": VERDICTS, "alignment_stats": c2.get("alignment_stats") or {}}
