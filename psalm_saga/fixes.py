"""Evaluation-guided fixes, applied as a new *version* of a run.

A fix never overwrites the run it was suggested for. The run folder is copied to a new version
(`<run>-v2`, `-v3`, …), the fix is applied there, and the pipeline redoes the work from the stage the
fix needs — every later stage runs again (conform, review with the design checklist, guard, analysis
of the synthetic text, evaluation). The original stays as it was, so the two versions can be compared
measure by measure and the better one kept.

Fix instructions live in their own setting (`stages.<stage>.params.fix_instruction`) and *replace*
the previous version's: instructions do not accumulate from one version to the next, so a redraft is
never told about numbers of a text that no longer exists. Instructions that older versions of the
software wrote into `extra_instruction` or `transform.notes` are removed when a version is made.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from psalm_saga.pipeline import STAGE_ORDER

FIX_KEYS = ("stages.draft.params.fix_instruction", "stages.plan.params.fix_instruction")


def combine_fixes(fixes: list[dict]) -> tuple[str, dict]:
    """The earliest stage any fix redoes, and the union of their overrides. Two fixes that give an
    instruction for the same setting (two redraft instructions, say) have their texts joined, so
    neither is lost; other values: the later fix wins."""
    order = {s: i for i, s in enumerate(STAGE_ORDER)}
    rerun_from = min((f["rerun_from"] for f in fixes), key=lambda s: order.get(s, 99))
    merged: dict = {}
    for f in fixes:
        for k, v in (f.get("overrides") or {}).items():
            if isinstance(v, str) and isinstance(merged.get(k), str) and v not in merged[k]:
                merged[k] = f"{merged[k]}\n\n{v}"
            else:
                merged[k] = v
    return rerun_from, merged


def base_id(run_id: str) -> str:
    return re.sub(r"-v\d+$", "", run_id)


def next_version_id(runs_dir: Path, run_id: str) -> tuple[str, int]:
    base = base_id(run_id)
    taken = [1]
    for p in runs_dir.glob(f"{base}-v*"):
        m = re.fullmatch(rf"{re.escape(base)}-v(\d+)", p.name)
        if m and (p / "run.json").exists():
            taken.append(int(m.group(1)))
    v = max(taken) + 1
    return f"{base}-v{v}", v


def _get(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set(cfg: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    if value is None:
        cur.pop(parts[-1], None)
    else:
        cur[parts[-1]] = value


def strip_fix_settings(config: dict, history: list[dict]) -> dict:
    """Remove what earlier fixes wrote into the configuration: the dedicated fix instructions, and —
    for runs fixed with older versions of the software — fix texts left in extra_instruction,
    transform.notes and stage parameters."""
    cfg = json.loads(json.dumps(config))
    for k in FIX_KEYS:
        _set(cfg, k, None)
    for h in history:
        for k, v in (h.get("overrides") or {}).items():
            cur = _get(cfg, k)
            if cur is None:
                continue
            if isinstance(v, str) and isinstance(cur, str):
                rest = "\n\n".join(p for p in cur.split("\n\n") if p.strip() and p.strip() not in v)
                _set(cfg, k, rest or None if k.endswith(("extra_instruction", "notes")) else rest)
                if k == "transform.notes" and not rest:
                    _set(cfg, k, "")
            elif cur == v:
                _set(cfg, k, None)
    return cfg


def make_version(runs_dir: Path, run_id: str, fixes: list[dict]) -> tuple[str, str, dict]:
    """Copy the run to a new version folder with the fixes applied to its configuration.
    Returns (new run id, stage to redo from, the overrides applied)."""
    src = runs_dir / run_id
    new_id, version = next_version_id(runs_dir, run_id)
    dst = runs_dir / new_id
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("calls", "events.jsonl", "*.graphml"))
    meta = json.loads((dst / "run.json").read_text(encoding="utf-8"))
    rerun_from, overrides = combine_fixes(fixes)
    cfg = strip_fix_settings(meta.get("config") or {}, meta.get("evaluation_guided_fixes") or [])
    for k, v in overrides.items():
        _set(cfg, k, v)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    parent_version = int(meta.get("version") or 1)
    history = list(meta.get("evaluation_guided_fixes") or [])
    history.append({"version": version, "at": now, "fixes": [f["id"] for f in fixes], "rerun_from": rerun_from,
                    "overrides": overrides,
                    "metrics": {k: v for f in fixes for k, v in (f.get("scores") or {}).items()}})
    meta.update(id=new_id, parent=run_id, root=base_id(run_id), version=version, parent_version=parent_version,
                fixes=[f["id"] for f in fixes], fix_titles=[f.get("title", f["id"]) for f in fixes],
                created=now, status="created", finished=None, error=None, current_stage=None,
                config=cfg, evaluation_guided_fixes=history,
                parent_usage=meta.get("usage") or {}, usage={}, timing={})
    (dst / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_id, rerun_from, overrides


def compare_evaluations(old: dict, new: dict) -> dict:
    """Per graded measure: score before, after and the change; plus counts over all and core measures."""
    from psalm_saga.eval.grading import CORE

    go, gn = old.get("grades") or {}, new.get("grades") or {}
    rows, better, worse, core_b, core_w = {}, 0, 0, 0, 0
    for k in set(go) | set(gn):
        a, b = (go.get(k) or {}).get("score"), (gn.get(k) or {}).get("score")
        if a is None or b is None or not (gn.get(k) or {}).get("grade"):
            continue
        d = round(b - a, 3)
        rows[k] = {"before": a, "after": b, "change": d}
        if d > 0.02:
            better += 1
            core_b += k in CORE
        elif d < -0.02:
            worse += 1
            core_w += k in CORE
    return {"measures": rows, "better": better, "worse": worse, "core_better": core_b, "core_worse": core_w}


def fix_context(store) -> dict:
    """What targeted fixes need to know, in *design* terms (renamed, transformed — never source names
    or wording, since the instructions go to stages behind the clean-room boundary):
    the design's events, causes, characters, places and relations that the analysis did not find in
    the synthetic text; each main character's gender; the function words most out of line."""
    from psalm_saga.artifacts import Bible, TransformMap
    from psalm_saga.graph import build_graph, compare_graphs

    out: dict = {}
    design = store.maybe("bible.json", Bible)
    src = store.maybe("bible_source.json", Bible)
    rec = store.maybe("recovered/bible_source.json", Bible)
    if design and src and rec:
        tmap = store.maybe("transform.json", TransformMap)
        g = compare_graphs(build_graph(src), build_graph(rec), tmap.as_dict() if tmap else {})
        dg = build_graph(design)
        dn = {n["id"]: n for n in dg["nodes"]}
        lab = lambda i: (dn.get(i) or {}).get("label", "")  # noqa: E731
        miss: dict[str, list[str]] = {"events": [], "characters": [], "places": [], "relations": [], "causes": []}
        for n in g["nodes"]:
            if n["status"] != "source_only" or n["id"] not in dn:
                continue
            d = dn[n["id"]]
            if n["type"] == "event":
                miss["events"].append(f"ch. {(d.get('chapters') or ['?'])[0]}: {(d.get('details') or {}).get('description', '')}")
            elif n["type"] == "character":
                miss["characters"].append(d["label"])
            elif n["type"] == "place":
                miss["places"].append(d["label"])
        for e in g["edges"]:
            if e["status"] != "source_only" or e["source"] not in dn or e["target"] not in dn:
                continue
            if e["type"] == "relation":
                de = next((x for x in dg["edges"] if x["type"] == "relation" and x["source"] == e["source"]
                           and x["target"] == e["target"]), None)
                miss["relations"].append(f"{lab(e['source'])} — {(de or e).get('label', '')} → {lab(e['target'])}")
            elif e["type"] == "causes":
                a = (dn[e["source"]].get("details") or {}).get("description", "")
                b = (dn[e["target"]].get("details") or {}).get("description", "")
                miss["causes"].append(f"{a} → leads to → {b}")
        out["missing"] = {k: v[:12] for k, v in miss.items() if v}
        out["genders"] = [{"name": e.name, "gender": e.gender} for e in sorted(design.characters(), key=lambda e: -e.mentions)
                          if e.gender in ("female", "male", "nonbinary")][:12]
    return out


def function_word_gaps(rows: list[dict], k: int = 8) -> list[str]:
    """The frequent words whose rate differs most between source and synthetic text (per 1,000 words)."""
    import math

    scored = []
    for r in rows or []:
        a, b = float(r.get("source") or 0), float(r.get("synthetic") or 0)
        if a < 2 and b < 2:
            continue
        scored.append((abs(math.log((a + 0.5) / (b + 0.5))), r["word"], a, b))
    return [f"“{w}”: {a:.0f} per 1,000 words in the source, {b:.0f} in the previous version"
            for _, w, a, b in sorted(scored, reverse=True)[:k]]
