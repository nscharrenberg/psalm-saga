"""Run bundles: one zip with everything needed to share or re-evaluate a run.

full     every file of the run directory, including the source text and everything derived
         from it. For internal use (re-evaluation, audits); it contains protected material.
release  only synthetic material: the story, the synthetic specification, bible, plan and
         graph, reviews, and an evaluation with every quotation of the source removed. This
         is what could go to researchers, subject to the library's own checks.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from psalm_saga.store import RunStore

# Files and folders derived from (or containing) the source text, excluded from a release.
SOURCE_DERIVED = ("input/", "notes/", "bible_source.json", "spec_source.json", "profile.json", "variety.json",
                  "transform.json", "guard.json", "events.jsonl", "graph-source.", "text_kind.json", "calibration/",
                  "calls/")  # full prompts contain the source


def _release_evaluation(ev: dict) -> dict:
    ev = json.loads(json.dumps(ev))
    leak = ev.get("leakage") or {}
    if "copied_spans" in leak:  # spans are source text by definition
        leak["copied_spans"] = [{"start": s.get("start"), "length": s.get("length")} for s in leak["copied_spans"]]
    leak.pop("name_leakage", None)  # original names
    var = ev.get("variety") or {}
    var.pop("standard_forms_in_synthetic", None)
    fid = ev.get("fidelity") or {}
    (fid.get("characters") or {}).pop("per_character", None)  # keyed by original names
    for row in (ev.get("distributions") or {}).get("characters", []):
        row.pop("name", None)
    return ev


def _datasheet(store: RunStore, release: bool) -> str:
    meta = store.meta()
    ev = store.read_json("evaluation.json") if store.exists("evaluation.json") else {}
    lines = [f"# Run {store.id}", "", f"Bundle: {'release (synthetic material only)' if release else 'full (includes the source text — internal use only)'}",
             f"Exported: {datetime.now(UTC).isoformat(timespec='seconds')}", f"Preset: {meta.get('preset')} · mode: {meta.get('mode')} · language: {meta.get('language')}", ""]
    cfg = meta.get("config") or {}
    pol = (cfg.get("transform") or {}).get("policy") or {}
    if pol:
        lines += ["## Transformation policy", ""] + [f"- {k.replace('_', ' ')}: {v}" for k, v in pol.items()] + [""]
    if ev:
        lines += ["## Measured properties (see evaluation.json)", ""]
        ln = ev.get("length") or {}
        lines.append(f"- length: {ln.get('words')} words, {ln.get('chapters')} chapters")
        lang = ev.get("language") or {}
        lines.append(f"- language: {lang.get('detected')} (expected {lang.get('expected')})")
        f = ev.get("fidelity") or {}
        if f:
            lines.append(f"- stylometric drift (0 = identical): {f.get('stylometric_mean_rel_diff')}")
            lines.append(f"- chapter structure equal: {(f.get('chapter_count') or {}).get('equal')}")
            ch = f.get("characters") or {}
            lines.append(f"- character salience ρ: {ch.get('salience_spearman')}, co-occurrence Jaccard: {ch.get('cooccurrence_jaccard')}")
        v = ev.get("variety") or {}
        if v.get("applicable"):
            lines.append(f"- language variety retention: {v.get('retention')} ({v.get('source_variety')})")
        lk = ev.get("leakage") or {}
        if lk:
            lines.append(f"- longest span shared with the source: {lk.get('longest_copied_span_words')} words; 8-gram overlap {lk.get('ngram8_overlap')}")
        lines.append("")
    lines += ["## Files", "", "story.md — the synthetic text; chapters/ — per chapter; spec.json, bible.json, plan.json — the synthetic design;",
              "graph-synthetic.graphml — knowledge graph; evaluation.json — measurements; run.json — configuration and usage."]
    fixes = meta.get("evaluation_guided_fixes") or []
    if fixes:
        lines += ["", f"Note: this run was revised {len(fixes)} time(s) using its own evaluation "
                  f"({', '.join(f['id'] for f in fixes)}). Its measurements are therefore not independent of the "
                  "generation and should not be pooled with unrevised runs in an experiment."]
    if not release:
        lines += ["", "This bundle CONTAINS THE SOURCE TEXT (input/source.txt) and material derived from it. Do not share it outside the institution."]
    return "\n".join(lines) + "\n"


def build_bundle(run_dir: str | Path, *, release: bool = False) -> bytes:
    store = RunStore(run_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(store.root.rglob("*")):
            if not p.is_file() or p.name.endswith(".tmp"):
                continue
            rel = p.relative_to(store.root).as_posix()
            if release and rel.startswith(SOURCE_DERIVED):
                continue
            if release and rel == "evaluation.json":
                z.writestr(rel, json.dumps(_release_evaluation(json.loads(p.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
            elif release and rel == "run.json":
                meta = json.loads(p.read_text(encoding="utf-8"))
                meta.pop("error", None)
                z.writestr(rel, json.dumps(meta, ensure_ascii=False, indent=2))
            else:
                z.write(p, rel)
        try:  # the knowledge graph as GraphML, ready for Gephi / networkx
            from psalm_saga.graph import to_graphml
            from psalm_saga.sdk import Saga

            run = Saga.open(store.root)
            if store.exists("bible.json"):
                z.writestr("graph-synthetic.graphml", to_graphml(run.graph("synthetic")))
            if not release and store.exists("bible_source.json"):
                z.writestr("graph-source.graphml", to_graphml(run.graph("source")))
                if store.exists("bible.json"):
                    z.writestr("graph-compare-design.graphml", to_graphml(run.graph("compare", against="design")))
                if run.recovered_bible() is not None:
                    z.writestr("graph-compare-text.graphml", to_graphml(run.graph("compare", against="text")))
        except Exception:
            pass
        z.writestr("README.md", _datasheet(store, release))
    return buf.getvalue()
