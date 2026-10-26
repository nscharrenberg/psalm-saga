"""Story knowledge graph: the story bible as nodes and typed edges.

Nodes
  character, place, object, organisation, other   entities of the story world
  scene                                           one per extracted scene  (id s<chapter>.<n>)
  event                                           one per plot event       (id v<chapter>.<n>)
  chapter                                         one per chapter          (id ch<n>)

Edges
  relation     entity -> entity, typed by the extracted relation ("mother of", "lives in");
               group "social" between characters, "world" when a place/object/organisation is involved
  co_occurs    character <-> character, weight = scenes (or chapters) shared
  appears_in   entity -> scene
  set_in       scene -> place     (from the scene's location, else its setting text)
  happens_at   event -> place
  involves     event -> character
  causes       event -> event     (explicit in-passage link, or inferred from the cause text: `inferred`)
  in_chapter   scene/event -> chapter
  next         scene -> following scene, chapter -> following chapter

Every node and edge carries the chapters it belongs to, so a viewer can filter by chapter.
"""

from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from xml.sax.saxutils import escape

from psalm_saga.artifacts import Bible, Entity, TransformMap

ENTITY_KINDS = ("character", "place", "object", "organisation", "other")
_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = set(["the", "a", "an", "of", "and", "to", "in", "on", "at", "with", "from", "by", "for", "his", "her", "their", "its", "was", "were", "is", "be", "de", "het", "een", "en", "van", "in", "op", "aan", "met", "te", "die", "dat", "der", "des", "den", "und", "die", "das", "ein", "eine", "zu", "im",
             # numerals: "de twee snorren" ~ "de snorren"
             "one", "two", "three", "four", "five", "twee", "drie", "vier", "vijf", "zwei", "drei", "fünf"])


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _tokens(s: str) -> set[str]:
    return {t for t in (w.lower() for w in _WORD.findall(s)) if len(t) > 2 and t not in _STOP}


class _Resolver:
    """Maps a name as written in a scene or event to an entity id."""

    def __init__(self, entities: list[Entity]):
        self.full: dict[str, str] = {}
        tokens: dict[str, set[str]] = defaultdict(set)
        for e in entities:
            for n in [e.name, *e.aliases]:
                if n.strip():
                    self.full.setdefault(_norm(n), e.id)
                    for t in n.split():
                        if len(t) > 2 and t[:1].isupper():
                            tokens[t.lower()].add(e.id)
        self.token = {t: next(iter(ids)) for t, ids in tokens.items() if len(ids) == 1}  # unambiguous only
        self.places = [(e.id, [n for n in [e.name, *e.aliases] if len(n) > 2]) for e in entities if e.kind == "place"]

    def __call__(self, name: str) -> str | None:
        n = _norm(name)
        if not n:
            return None
        if n in self.full:
            return self.full[n]
        for t in name.split():
            if t.lower() in self.token:
                return self.token[t.lower()]
        return None

    def place_in(self, text: str) -> str | None:
        for eid, names in self.places:
            for n in names:
                if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE):
                    return eid
        return None


def build_graph(bible: Bible, *, counterpart: dict[str, str] | None = None, max_cause_links: int = 1) -> dict:
    """Build the graph. `counterpart` maps entity names to their name in the other text (source <-> synthetic)."""
    resolve = _Resolver(bible.entities)
    kind = {e.id: e.kind for e in bible.entities}
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def edge(src: str, dst: str, typ: str, *, label: str = "", chapters=(), weight: float = 1, directed=True, **extra):
        if src not in nodes or dst not in nodes or src == dst:
            return
        a, b = (src, dst) if directed else tuple(sorted((src, dst)))
        key = f"{typ}:{a}:{b}:{label}"
        if key in edges:
            e = edges[key]
            e["weight"] += weight
            e["chapters"] = sorted(set(e["chapters"]) | set(chapters))
            return
        edges[key] = {"id": f"x{len(edges)}", "source": a, "target": b, "type": typ, "label": label,
                      "weight": weight, "chapters": sorted(set(chapters)), "directed": directed, **extra}

    for e in bible.entities:
        nodes[e.id] = {"id": e.id, "type": e.kind if e.kind in ENTITY_KINDS else "other", "label": e.name,
                       "chapters": sorted(e.chapters), "weight": max(e.mentions, 1),
                       "details": {"aliases": e.aliases, "description": e.description, "role": e.role,
                                   "mentions": e.mentions,
                                   "counterpart": (counterpart or {}).get(e.name, "")}}
    for r in bible.relations:
        group = "social" if kind.get(r.source) == kind.get(r.target) == "character" else "world"
        edge(r.source, r.target, "relation", label=r.type, group=group, description=r.description,
             chapters=sorted(set(nodes.get(r.source, {}).get("chapters", [])) & set(nodes.get(r.target, {}).get("chapters", []))))

    prev_scene, prev_chapter = None, None
    scene_cast: list[tuple[int, set[str]]] = []
    for ch in bible.chapters:
        cid = f"ch{ch.index}"
        nodes[cid] = {"id": cid, "type": "chapter", "label": f"{ch.index}. {ch.title}".strip(". ") if ch.title else str(ch.index),
                      "chapters": [ch.index], "weight": max(ch.word_count, 1),
                      "details": {"summary": ch.summary, "word_count": ch.word_count, "scenes": len(ch.scenes),
                                  "events": len(ch.events)}}
        if prev_chapter:
            edge(prev_chapter, cid, "next", chapters=[ch.index])
        prev_chapter = cid
        for i, sc in enumerate(ch.scenes, 1):
            sid = f"s{ch.index}.{i}"
            nodes[sid] = {"id": sid, "type": "scene", "label": f"Scene {ch.index}.{i}", "chapters": [ch.index], "weight": 1,
                          "details": {"summary": sc.summary, "setting": sc.setting, "purpose": sc.purpose, "pov": sc.pov,
                                      "characters": sc.characters, "location": sc.location}}
            edge(sid, cid, "in_chapter", chapters=[ch.index])
            if prev_scene:
                edge(prev_scene, sid, "next", chapters=[ch.index])
            prev_scene = sid
            cast = {eid for eid in (resolve(n) for n in sc.characters) if eid}
            for eid in cast:
                edge(eid, sid, "appears_in", chapters=[ch.index])
            scene_cast.append((ch.index, {c for c in cast if kind.get(c) == "character"}))
            place = (resolve(sc.location) if sc.location else None) or resolve.place_in(f"{sc.setting} {sc.summary}")
            if place and kind.get(place) == "place":
                edge(sid, place, "set_in", chapters=[ch.index])
        for i, ev in enumerate(ch.events, 1):
            vid = f"v{ch.index}.{i}"
            nodes[vid] = {"id": vid, "type": "event", "label": f"Event {ch.index}.{i}", "chapters": [ch.index], "weight": 1,
                          "details": {"description": ev.description, "caused_by": ev.caused_by,
                                      "characters": ev.characters, "location": ev.location}}
            edge(vid, cid, "in_chapter", chapters=[ch.index])
            for eid in (resolve(n) for n in ev.characters):
                if eid:
                    edge(vid, eid, "involves", chapters=[ch.index])
            place = (resolve(ev.location) if ev.location else None)
            if place and kind.get(place) == "place":
                edge(vid, place, "happens_at", chapters=[ch.index])
            if ev.cause_index is not None and 0 <= ev.cause_index < i - 1:
                edge(f"v{ch.index}.{ev.cause_index + 1}", vid, "causes", chapters=[ch.index], inferred=False)
        nodes_events = [(n["id"], _tokens(n["details"]["description"])) for n in nodes.values() if n["type"] == "event"]
        for i, ev in enumerate(ch.events, 1):  # cause given as text: link to the most similar earlier event
            vid = f"v{ch.index}.{i}"
            if ev.cause_index is not None or not ev.caused_by.strip():
                continue
            want = _tokens(ev.caused_by)
            scored = []
            for other, toks in nodes_events:
                if other == vid:
                    break  # only earlier events
                if want and toks:
                    j = len(want & toks) / len(want | toks)
                    if j >= 0.25:
                        scored.append((j, other))
            for _j, other in sorted(scored, reverse=True)[:max_cause_links]:
                edge(other, vid, "causes", chapters=[ch.index], inferred=True)

    # Co-occurrence: shared scenes when scenes list their cast, else shared chapters.
    if any(cast for _, cast in scene_cast):
        for chap, cast in scene_cast:
            for a, b in combinations(sorted(cast), 2):
                edge(a, b, "co_occurs", chapters=[chap], directed=False)
    else:
        chars = [e for e in bible.entities if e.kind == "character"]
        for a, b in combinations(chars, 2):
            shared = sorted(set(a.chapters) & set(b.chapters))
            if shared:
                edge(a.id, b.id, "co_occurs", chapters=shared, weight=len(shared), directed=False)

    counts: dict[str, int] = defaultdict(int)
    for n in nodes.values():
        counts[n["type"]] += 1
    ecounts: dict[str, int] = defaultdict(int)
    for e in edges.values():
        ecounts[e["type"] + (f":{e['group']}" if e.get("group") else "")] += 1
    return {"nodes": list(nodes.values()), "edges": list(edges.values()),
            "chapters": [c.index for c in bible.chapters], "counts": dict(counts), "edge_counts": dict(ecounts)}


def counterpart_map(tmap: TransformMap | None, which: str) -> dict[str, str]:
    if not tmap:
        return {}
    pairs = tmap.as_dict()
    return pairs if which == "source" else {v: k for k, v in pairs.items()}


STORY_TYPES = ("chapter", "scene", "event")
STATUSES = ("kept", "changed", "source_only", "synthetic_only")


def _names(n: dict) -> list[str]:
    return [n["label"], *((n.get("details") or {}).get("aliases") or [])]


_POSS = re.compile(r"(?:'s|’s|s'|s’)(?!\w)")


def _key(name: str, owners: frozenset[str] = frozenset()) -> str:
    """Order-free content words of a name: no articles, possessives or case, and no owner
    (a character's name, also in the s-genitive without apostrophe of Dutch and German:
    "Roberts paraplu" ~ "de paraplu", "George's chest" ~ "the chest")."""
    toks = _tokens(_POSS.sub("", name))
    rest = {t for t in toks if t not in owners and not (t.endswith("s") and t[:-1] in owners)}
    return " ".join(sorted(rest or toks))


_LOOSE = {"object", "organisation", "other"}


def _compatible(a: str, b: str) -> bool:
    """Characters and places must stay what they are; objects, organisations and "other" are
    often classified differently by two independent analyses of the same thing."""
    return a == b or (a in _LOOSE and b in _LOOSE)


def _same_label(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if a == b or (a and b and (a in b or b in a)):
        return True
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb and len(ta & tb) / len(ta | tb) >= 0.5)


_SUFFIXES = ("tjes", "jes", "tje", "je", "en", "es", "er", "e", "n", "s")  # plural/diminutive endings (nl, en, de)


def _stem(t: str) -> str:
    for suf in _SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            t = t[: -len(suf)]
            break
    if len(t) > 3 and t[-1] == t[-2] and t[-1] not in "aeiou":  # "stokk" -> "stok"
        t = t[:-1]
    return t


def _tok_match(a: str, b: str) -> bool:
    """Same word up to inflection: equal, equal after removing a plural or diminutive ending
    ("stok"/"stokken", "paard"/"paardje", "snorren"/"snor"), or sharing a start that covers most of
    the longer word ("marsepein"/"marsepeinen", "chocola"/"chocolade") — but "trommel" is not
    "trommelstok"."""
    if a == b or _stem(a) == _stem(b):
        return True
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n >= max(5, 0.7 * max(len(a), len(b)))


def _fuzzy_jaccard(ta: set[str], tb: set[str]) -> float:
    if not ta or not tb:
        return 0.0
    hits = sum(any(_tok_match(a, b) for b in tb) for a in ta)
    hits_b = sum(any(_tok_match(b, a) for a in ta) for b in tb)
    inter = min(hits, hits_b)
    return inter / (len(ta) + len(tb) - inter)


def _align_sequence(sa: list[str], sb: list[str], sim, threshold: float) -> list[tuple[str, str]]:
    """Order-preserving alignment of two sequences (scenes or events of one chapter) that maximises
    the summed similarity of the pairs; items may stay unpaired, so a scene split in two, a merged
    pair or an extra event shifts nothing else (unlike pairing by position)."""
    n, k = len(sa), len(sb)
    score = [[0.0] * (k + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, k + 1):
            best = max(score[i - 1][j], score[i][j - 1])
            s_ij = sim(sa[i - 1], sb[j - 1])
            if s_ij >= threshold:
                best = max(best, score[i - 1][j - 1] + s_ij)
            score[i][j] = best
    pairs, i, j = [], n, k
    while i > 0 and j > 0:
        s_ij = sim(sa[i - 1], sb[j - 1])
        if s_ij >= threshold and abs(score[i][j] - (score[i - 1][j - 1] + s_ij)) < 1e-9:
            pairs.append((sa[i - 1], sb[j - 1]))
            i, j = i - 1, j - 1
        elif score[i][j] == score[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def compare_graphs(src: dict, syn: dict, mapping: dict[str, str], *, prealign: list[tuple[str, str]] | None = None,
                   checks: dict[str, dict] | None = None) -> dict:
    """Align a source graph with a synthetic one and mark what is kept, changed, or missing.

    `syn` is either the synthetic *design* (bible.json: same ids as the source by construction)
    or the graph *re-extracted from the synthetic text* (independent ids). Entities are aligned
    by id when the ids carry the same name mapping, else through the rename table
    (source name -> synthetic name, matched against names and aliases). Chapters align by number;
    scenes and events align within their chapter by content (what happens, who takes part, where),
    in story order, allowing splits, merges and extra items.

    The result is one merged graph in source coordinates: every node and edge has a `status`
    (kept / changed / source_only / synthetic_only) and a `diff` note; synthetic-only nodes get
    ids prefixed with `y:`. `summary` counts statuses per node and edge type, and gives recall /
    precision of entities and of each edge type.

    `prealign` gives pairs (source id, synthetic id) established elsewhere — by the model alignment
    of psalm_saga.eval.kg_align — which take precedence over the rules; a source id given twice
    absorbs the second synthetic item (one scene told in two parts). `checks` marks source items
    the analysis did not find but a direct check of the synthetic text did: keys are node ids, or
    `edge:<type>:<source>:<target>` for links; values {"realised": "yes" | "partly", "evidence": "…"}."""
    from psalm_saga.stages.transform import apply_renames

    sn = {n["id"]: n for n in src["nodes"]}
    yn = {n["id"]: n for n in syn["nodes"]}
    m = {_norm(k): _norm(v) for k, v in mapping.items()}
    # Character name words on both sides (and the rename table), to strip owners from object names.
    owners = frozenset(t for g in (src, syn) for n in g["nodes"] if n["type"] == "character"
                       for nm in _names(n) for t in _tokens(nm)) | frozenset(
        t for k, v in mapping.items() for t in _tokens(f"{k} {v}"))
    y_by_name: dict[str, str] = {}
    y_by_key: dict[str, str] = {}
    y_by_bare: dict[str, list[str]] = defaultdict(list)
    for n in syn["nodes"]:
        if n["type"] not in STORY_TYPES:
            for nm in _names(n):
                y_by_name.setdefault(_norm(nm), n["id"])
                if k := _key(nm):
                    y_by_key.setdefault(k, n["id"])
                if n["type"] != "character" and (k := _key(nm, owners)) and n["id"] not in y_by_bare[k]:
                    y_by_bare[k].append(n["id"])

    def translations(n: dict) -> list[str]:
        """The source entity's names as they should read in the synthetic text: the rename table
        applied to whole names *and inside other names* ("George's chest" -> "Nathaniel's chest"),
        exactly as the transform stage renamed the design."""
        out = []
        for nm in _names(n):
            out += [m.get(_norm(nm), ""), _norm(apply_renames(nm, mapping)), _norm(nm)]
        return [t for t in dict.fromkeys(out) if t]

    align: dict[str, str] = {}  # source id -> synthetic id
    taken: set[str] = set()
    absorbed: dict[str, str] = {}  # synthetic part of a split -> the source item it belongs to
    for a, b in prealign or []:
        if a not in sn or b not in yn or b in taken:
            continue
        if a not in align:
            align[a] = b
            taken.add(b)
        elif sn[a]["type"] in ("scene", "event"):
            absorbed[b] = a
            taken.add(b)
    for n in src["nodes"]:
        if n["type"] in STORY_TYPES or n["id"] in align:
            continue
        names = translations(n)
        cand = next((y_by_name[t] for t in names if t in y_by_name and y_by_name[t] not in taken), None)
        if cand is None:  # same words up to articles and possessives ("the chest of Nathaniel" ~ "Nathaniel's chest")
            cand = next((y_by_key[k] for t in names if (k := _key(t)) and k in y_by_key and y_by_key[k] not in taken), None)
        if cand is None and n["type"] != "character":  # same thing without its owner ("Roberts hoed" ~ "de hoed"), if unique
            for t in names:
                hits = [i for i in y_by_bare.get(_key(t, owners), []) if i not in taken and _compatible(n["type"], yn[i]["type"])]
                if len(hits) == 1:
                    cand = hits[0]
                    break
        if cand is None and n["id"] in yn and yn[n["id"]]["type"] == n["type"]:
            other = yn[n["id"]]
            if (other.get("details") or {}).get("counterpart") or _norm(other["label"]) == m.get(_norm(n["label"])):
                cand = n["id"]
        if cand:
            align[n["id"]] = cand
            taken.add(cand)

    # Second pass for what names alone could not pair (two independent analyses word things
    # differently): same kind, overlapping name words after renaming, similar description, and
    # attached to the same already-aligned neighbours. Greedy, best score first.
    def nbrs(g: dict, i: str) -> set[str]:
        return {e["target"] if e["source"] == i else e["source"] for e in g["edges"]
                if e["type"] == "relation" and i in (e["source"], e["target"])}

    def ties(g: dict, i: str, via: dict[str, str] | None = None) -> set[tuple[str, str]]:
        """(neighbour, relation label) pairs, neighbours translated to synthetic ids when `via` is given."""
        out = set()
        for e in g["edges"]:
            if e["type"] == "relation" and i in (e["source"], e["target"]):
                o = e["target"] if e["source"] == i else e["source"]
                o = via.get(o) if via is not None else o
                if o:
                    out.add((o, _norm(e.get("label", ""))))
        return out

    s_left = [n for n in src["nodes"] if n["type"] not in STORY_TYPES and n["id"] not in align]
    y_left = [n for n in syn["nodes"] if n["type"] not in STORY_TYPES and n["id"] not in taken]
    scored = []
    for a in s_left:
        ta_names = [toks for t in translations(a) if (toks := _tokens(t))]
        da = _tokens((a.get("details") or {}).get("description") or "")
        na = {align[x] for x in nbrs(src, a["id"]) if x in align}
        for b in y_left:
            if not _compatible(a["type"], b["type"]):
                continue
            tb_names = [toks for t in _names(b) if (toks := _tokens(_norm(t)))]
            db = _tokens((b.get("details") or {}).get("description") or "")
            # best pair of names (an alias must not dilute the match)
            name = max((_fuzzy_jaccard(x, y) for x in ta_names for y in tb_names), default=0.0)
            desc = len(da & db) / len(da | db) if da and db else 0.0
            shared = bool(na & nbrs(syn, b["id"]))
            # the same relation to the same (already aligned) neighbour: "the boy attached to George"
            # and "Helmsman Boy" are both "fond of" George's counterpart
            same_tie = bool(ties(src, a["id"], align) & ties(syn, b["id"]))
            ca, cb = set(a.get("chapters") or []), set(b.get("chapters") or [])
            chap = len(ca & cb) / len(ca | cb) if ca and cb else 0.0  # objects tend to belong to their chapters
            score = (name + 0.5 * desc + (0.25 if shared else 0) + (0.3 if same_tie else 0) + 0.2 * chap
                     - (0.1 if a["type"] != b["type"] else 0))
            if score >= 0.55 and (name > 0 or same_tie or (shared and desc >= 0.3)):
                scored.append((score, a["id"], b["id"]))
    for _sc, a, b in sorted(scored, reverse=True):
        if a not in align and b not in taken:
            align[a] = b
            taken.add(b)

    # Story nodes. Chapters by number; scenes and events within a chapter by content.
    for n in src["nodes"]:
        if n["type"] == "chapter" and n["id"] in yn and yn[n["id"]]["type"] == "chapter":
            align[n["id"]] = n["id"]

    def people(g: dict, i: str, via: dict[str, str] | None) -> set[str]:
        out = set()
        for e in g["edges"]:
            if e["type"] in ("appears_in", "involves", "set_in", "happens_at") and i in (e["source"], e["target"]):
                o = e["target"] if e["source"] == i else e["source"]
                o = via.get(o) if via is not None else o
                if o:
                    out.add(o)
        return out

    def story_text(n: dict, translate: bool) -> set[str]:
        d = n.get("details") or {}
        txt = " ".join(str(d.get(k) or "") for k in ("summary", "setting", "description", "caused_by"))
        return _tokens(apply_renames(txt, mapping) if translate else txt)

    s_text = {n["id"]: story_text(n, True) for n in src["nodes"] if n["type"] in ("scene", "event")}
    y_text = {n["id"]: story_text(n, False) for n in syn["nodes"] if n["type"] in ("scene", "event")}
    s_ppl = {i: people(src, i, align) for i in s_text}
    y_ppl = {i: people(syn, i, None) for i in y_text}

    def story_sim(a: str, b: str) -> float:
        t = _fuzzy_jaccard(s_text[a], y_text[b])
        pa, pb = s_ppl[a], y_ppl[b]
        p = len(pa & pb) / len(pa | pb) if pa and pb else t
        return 0.65 * t + 0.35 * p

    def in_chapter(g: dict, typ: str) -> dict[int, list[str]]:
        out: dict[int, list[str]] = defaultdict(list)
        for n in g["nodes"]:
            if n["type"] == typ:
                out[(n.get("chapters") or [0])[0]].append(n["id"])
        for v in out.values():
            v.sort(key=lambda i: int(i.split(".")[-1]) if i.split(".")[-1].isdigit() else 0)
        return out

    for typ in ("scene", "event"):
        sa, ya = in_chapter(src, typ), in_chapter(syn, typ)
        for ch in set(sa) | set(ya):
            pairs = _align_sequence([i for i in sa.get(ch, []) if i not in align],
                                    [i for i in ya.get(ch, []) if i not in taken], story_sim, 0.12)
            for a, b in pairs:
                align[a] = b
                taken.add(b)
            # an unpaired synthetic item right next to a paired one, and similar to its source
            # item, is the other half of a split (one scene told as two): part of that item
            paired = dict((b, a) for a, b in pairs)
            seq = ya.get(ch, [])
            for idx, b in enumerate(seq):
                if b in paired:
                    continue
                for nb in (seq[idx - 1] if idx else None, seq[idx + 1] if idx + 1 < len(seq) else None):
                    if nb in paired and story_sim(paired[nb], b) >= 0.2:
                        absorbed[b] = paired[nb]
                        break
    back = {v: k for k, v in align.items()}
    for b, a in absorbed.items():
        back.setdefault(b, a)

    def yid(i: str) -> str:
        return back.get(i, f"y:{i}")

    def ekey(e: dict, a: str, b: str) -> tuple:
        if not e.get("directed", True):
            a, b = sorted((a, b))
        return (e["type"], e.get("group", ""), a, b)

    s_edges: dict[tuple, dict] = {}
    for e in src["edges"]:
        s_edges.setdefault(ekey(e, e["source"], e["target"]), e)
    y_edges: dict[tuple, dict] = {}
    for e in syn["edges"]:
        y_edges.setdefault(ekey(e, yid(e["source"]), yid(e["target"])), e)

    def neigh(edges: dict[tuple, dict], node: str, types: tuple[str, ...]) -> set[str]:
        out = set()
        for (t, _g, a, b) in edges:
            if t in types:
                if a == node:
                    out.add(b)
                elif b == node:
                    out.add(a)
        return out

    nodes, summary_n = [], defaultdict(lambda: dict.fromkeys(STATUSES, 0))
    for n in src["nodes"]:
        d = dict(n, details=dict(n.get("details") or {}))
        if n["id"] not in align:
            d["status"], d["diff"] = "source_only", "not found in the synthetic graph"
            ck = (checks or {}).get(n["id"])
            if ck and ck.get("realised") in ("yes", "partly"):
                d["status"] = "kept" if ck["realised"] == "yes" else "changed"
                d["diff"] = (f"(found by checking the text — the analysis had missed it: “{ck.get('evidence', '')}”)"
                             if ck["realised"] == "yes" else f"only partly realised in the text: “{ck.get('evidence', '')}”")
                d["details"]["checked"] = ck
        else:
            o = yn[align[n["id"]]]
            notes, remarks = [], []  # notes make it "changed"; remarks are shown but do not
            if o["type"] != n["type"]:
                # two analyses often classify the same thing differently (a rider as a character
                # or an object); only a person becoming a place, or vice versa, is a change
                (notes if {n["type"], o["type"]} <= {"character", "place"} else remarks).append(
                    f"classified as {o['type']} in the other analysis")
            if n["type"] in ("scene", "event"):
                types = ("appears_in", "involves", "set_in", "happens_at")
                a, b = neigh(s_edges, n["id"], types), neigh(y_edges, n["id"], types)
                is_char = lambda x: (sn.get(x) or (yn.get(x[2:]) if x.startswith("y:") else None) or {}).get("type") == "character"  # noqa: E731
                ca_, cb_ = {x for x in a if is_char(x)}, {x for x in b if is_char(x)}
                lost = [sn[x]["label"] for x in a - b if x in sn]
                new = [yn[x[2:]]["label"] if x.startswith("y:") and x[2:] in yn else sn.get(x, {}).get("label", x) for x in b - a]
                overlap = len(ca_ & cb_) / len(ca_ | cb_) if ca_ | cb_ else 1.0  # the cast; places are often worded differently
                txt = (lost and f"lost {', '.join(lost[:4])}") or ""
                txt += ("; " if txt and new else "") + (f"new {', '.join(new[:4])}" if new else "")
                # most of the cast or the place differs: a change; a minor figure more or less: a remark
                if ca_ and cb_ and overlap < 0.5:
                    notes.append("mostly different people: " + txt)
                elif txt:
                    remarks.append(txt)
                parts = [k for k, v in absorbed.items() if v == n["id"]]
                if parts:
                    remarks.append(f"told in {len(parts) + 1} parts in the other text")
            elif n["type"] not in STORY_TYPES:
                ca, cb = set(n.get("chapters") or []), set(o.get("chapters") or [])
                from psalm_saga.stages.transform import is_name_form

                # chapter presence is counted by literal name matches; for descriptions such as
                # "de moeder" it is unreliable (any mother counts), so only proper names are judged
                if ca and cb and len(ca & cb) / len(ca | cb) < 0.5:
                    (notes if is_name_form(n["label"]) else remarks).append(
                        f"appears in chapters {sorted(cb)[:8]} instead of {sorted(ca)[:8]}")
            d["status"] = "changed" if notes else "kept"
            d["diff"] = "; ".join(notes + [f"({r})" for r in remarks])
            if o["label"] != n["label"] and n["type"] not in STORY_TYPES:
                d["details"]["counterpart"] = o["label"]
            d["details"]["synthetic"] = {k: (o.get("details") or {}).get(k) for k in ("description", "summary", "role")
                                         if (o.get("details") or {}).get(k)}
        summary_n[n["type"]][d["status"]] += 1
        nodes.append(d)
    for n in syn["nodes"]:
        if n["id"] in back or n["id"] in absorbed:
            continue
        d = dict(n, id=f"y:{n['id']}", status="synthetic_only", diff="only in the synthetic graph",
                 details=dict(n.get("details") or {}))
        summary_n[n["type"]]["synthetic_only"] += 1
        nodes.append(d)
    ids = {n["id"] for n in nodes}

    edges, summary_e = [], defaultdict(lambda: dict.fromkeys(STATUSES, 0))
    for k, e in s_edges.items():
        o = y_edges.get(k)
        reversed_ = False
        if o is None and e["type"] == "relation":  # same pair, reversed direction
            o = y_edges.get((k[0], k[1], k[3], k[2]))
            reversed_ = o is not None
        status, diff = ("source_only", "not in the synthetic graph") if o is None else ("kept", "")
        if o is None:
            ck = (checks or {}).get(f"edge:{e['type']}:{e['source']}:{e['target']}")
            if ck and ck.get("realised") in ("yes", "partly"):
                status = "kept" if ck["realised"] == "yes" else "changed"
                diff = f"(found by checking the text: “{ck.get('evidence', '')}”)"
        if o is not None and e["type"] == "relation" and not _same_label(o.get("label", ""), e.get("label", "")):
            if reversed_:  # "mother of" one way, "daughter of" the other: the same tie, worded from the other side
                diff = f"(stated from the other side: “{o.get('label')}”)"
            else:
                status, diff = "changed", f"“{e.get('label')}” → “{o.get('label')}”"
        key = e["type"] + (f":{e['group']}" if e.get("group") else "")
        summary_e[key][status] += 1
        edges.append(dict(e, status=status, diff=diff))
    seen = set(s_edges) | {(k[0], k[1], k[3], k[2]) for k in s_edges if k[0] == "relation"}
    for k, e in y_edges.items():
        if k in seen:
            continue
        a, b = yid(e["source"]), yid(e["target"])
        if a not in ids or b not in ids:
            continue
        key = e["type"] + (f":{e['group']}" if e.get("group") else "")
        summary_e[key]["synthetic_only"] += 1
        edges.append(dict(e, id=f"y{e['id']}", source=a, target=b, status="synthetic_only", diff="only in the synthetic graph"))

    def pr(c: dict) -> dict:
        both = c["kept"] + c["changed"]
        rec = both / (both + c["source_only"]) if both + c["source_only"] else None
        prec = both / (both + c["synthetic_only"]) if both + c["synthetic_only"] else None
        return {**c, "recall": None if rec is None else round(rec, 3), "precision": None if prec is None else round(prec, 3)}

    counts: dict[str, int] = defaultdict(int)
    for n in nodes:
        counts[n["type"]] += 1
    ecounts: dict[str, int] = defaultdict(int)
    for e in edges:
        ecounts[e["type"] + (f":{e['group']}" if e.get("group") else "")] += 1
    return {"nodes": nodes, "edges": edges, "chapters": sorted(set(src.get("chapters", [])) | set(syn.get("chapters", []))),
            "counts": dict(counts), "edge_counts": dict(ecounts), "compare": True, "alignment": dict(align),
            "summary": {"nodes": {k: pr(v) for k, v in summary_n.items()}, "edges": {k: pr(v) for k, v in summary_e.items()}}}


def to_graphml(graph: dict) -> str:
    """GraphML for Gephi, Cytoscape desktop, yEd or networkx."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
           '<key id="label" for="node" attr.name="label" attr.type="string"/>',
           '<key id="type" for="node" attr.name="type" attr.type="string"/>',
           '<key id="weight" for="node" attr.name="weight" attr.type="double"/>',
           '<key id="chapters" for="node" attr.name="chapters" attr.type="string"/>',
           '<key id="description" for="node" attr.name="description" attr.type="string"/>',
           '<key id="etype" for="edge" attr.name="type" attr.type="string"/>',
           '<key id="elabel" for="edge" attr.name="label" attr.type="string"/>',
           '<key id="eweight" for="edge" attr.name="weight" attr.type="double"/>',
           '<key id="inferred" for="edge" attr.name="inferred" attr.type="boolean"/>',
           '<key id="status" for="all" attr.name="status" attr.type="string"/>',
           '<graph id="story" edgedefault="directed">']
    for n in graph["nodes"]:
        d = n.get("details", {})
        desc = d.get("description") or d.get("summary") or ""
        out.append(f'<node id="{escape(n["id"])}"><data key="label">{escape(n["label"])}</data>'
                   f'<data key="type">{n["type"]}</data><data key="weight">{n["weight"]}</data>'
                   f'<data key="chapters">{",".join(map(str, n["chapters"]))}</data>'
                   f'<data key="description">{escape(desc)}</data>'
                   + (f'<data key="status">{n["status"]}</data>' if n.get("status") else "") + '</node>')
    for e in graph["edges"]:
        directed = "true" if e.get("directed", True) else "false"
        out.append(f'<edge id="{e["id"]}" source="{escape(e["source"])}" target="{escape(e["target"])}" directed="{directed}">'
                   f'<data key="etype">{e["type"]}</data><data key="elabel">{escape(e.get("label", ""))}</data>'
                   f'<data key="eweight">{e["weight"]}</data>'
                   f'<data key="inferred">{"true" if e.get("inferred") else "false"}</data>'
                   + (f'<data key="status">{e["status"]}</data>' if e.get("status") else "") + '</edge>')
    out += ["</graph>", "</graphml>"]
    return "\n".join(out)
