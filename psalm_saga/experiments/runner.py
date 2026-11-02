"""Experiment grid runner.

    name: pilot
    output: experiments_out/pilot
    inputs:
      - {glob: "corpus/nl/*.txt", kind: source}
    conditions:
      full:       {preset: full}
      paraphrase: {preset: paraphrase}
      no_review:  {preset: full, overrides: {stages.review.enabled: false}}
    models:
      sonnet:  {models.default.name: anthropic/claude-sonnet-5-5}
      mistral: {models.default.name: mistral/mistral-large-latest}
    repeats: 1
    concurrency: 2
    overrides: {limits.max_cost_usd: 5}
    judge: {model: openai/gpt-5.5, instruments: [spec_recovery, quality_pairwise], quality_baseline: paraphrase}
    metadata: corpus/metadata.csv          # item,title,author,period,... (item = file stem)
    analyses:                               # R3: pre-registered analyses, run on both corpora
      - {feature: mean_sentence_words, by: period, groups: [1880, 1920]}
      - {feature: female_mention_share, vs: year}
    tstr_label: period                      # R5: train on synthetic, test on real

Every job is a normal run directory with a deterministic id
(<item>--<condition>--<model>--r<k>), so re-running the command resumes: finished
jobs are skipped, interrupted ones continue from their last finished stage/chapter.
"""

from __future__ import annotations

import asyncio
import csv
import glob
import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from psalm_saga.artifacts import Spec
from psalm_saga.config import load_config
from psalm_saga.eval import judges
from psalm_saga.pipeline import Pipeline
from psalm_saga.store import RunStore
from psalm_saga.taxonomy import load_taxonomy


class InputSpec(BaseModel):
    glob: str | None = None
    path: str | None = None
    kind: str = "source"  # source | premise | spec


class Condition(BaseModel):
    preset: str = "full"
    overrides: dict = Field(default_factory=dict)
    repeats: int | None = None  # samples per item for this condition (default: the plan's `repeats`)
    # with plan-level `policies`: the policy settings this condition runs under (default: all of them)
    policies: list[str] | None = None
    base: str | None = None  # set when crossed with a policy: the condition's own name
    policy: str | None = None  # set when crossed with a policy: the policy setting's name


JUDGE_INSTRUMENTS = ("spec_recovery", "dimension_fidelity", "quality_pairwise", "emotional_arc", "surface_reuse",
                     "reconstruction", "psalm_check", "psalm_anchor", "alignment_anchor")


class JudgeSpec(BaseModel):
    model: str | None = None
    instruments: list[str] = Field(default_factory=lambda: ["spec_recovery"])
    quality_baseline: str | None = None
    dimension_fidelity_max_words: int = 12000
    arc_segments: int = 10
    reuse_samples: int = 3
    # validity checks of the model-based primary measures (psalm_saga/eval/validity.py)
    # further judges for psalm_check, each of a model family other than the writers' and the primary judge's
    check_models: list[str] = Field(default_factory=list)
    check_model: str | None = None  # one further judge (older plans); merged into check_models
    anchor_condition: str = "full"  # the condition whose runs get the lower anchors

    def further_judges(self) -> list[str]:
        out = list(self.check_models)
        if self.check_model and self.check_model not in out:
            out.insert(0, self.check_model)
        return out


class ExperimentPlan(BaseModel):
    name: str
    output: str | None = None
    inputs: list[InputSpec]
    conditions: dict[str, Condition]
    models: dict[str, dict] = Field(default_factory=lambda: {"default": {}})
    repeats: int = 1
    concurrency: int = 2
    overrides: dict = Field(default_factory=dict)
    judge: JudgeSpec = Field(default_factory=JudgeSpec)
    limit_items: int | None = None
    metadata: str | None = Field(None, description="CSV with an `item` (file stem) column and covariates.")
    analyses: list[dict] = Field(default_factory=list, description="R3 analyses: {feature, by, groups} or {feature, vs}.")
    tstr_label: str | None = Field(None, description="R5: metadata column to predict.")
    # Policy settings crossed with the conditions: {name: {dimension: preserve | abstract | regenerate}}; a
    # condition then runs once per setting, as `<condition>@<setting>`. `all: <policy>` sets every dimension.
    policies: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Pre-registered tests (experiments/hypotheses.py), or "default": the paper's five families, generated
    # from the conditions' presets and the policy settings (default_hypotheses).
    hypotheses: list[dict] | str = Field(default_factory=list)
    margins: dict[str, float] = Field(default_factory=dict, description="Override the default margins of `default`.")
    alpha: float = 0.05
    bootstrap: int = 10000
    period_split: dict | None = Field(None, description="Derive a two-level `period` column: {from: year, at: median "
                                      "| <number>}; items at or before the split are `early`, after it `late`.")


@dataclass
class Job:
    item: str
    path: Path
    kind: str
    condition: str
    model: str
    repeat: int

    @property
    def run_id(self) -> str:
        return f"{self.item}--{self.condition}--{self.model}--r{self.repeat}"


def _slug(p: Path) -> str:
    return re.sub(r"[^\w.-]+", "_", p.stem)[:80]


DIMENSIONS = ("writing_style", "narrative_voice", "character", "plot_structure", "scene_sequence", "world_building")


def policy_setting(spec: dict[str, str]) -> dict[str, str]:
    base = {d: spec.get("all", "preserve") for d in DIMENSIONS}
    return {**base, **{k: v for k, v in spec.items() if k != "all"}}


def materialise(plan: ExperimentPlan) -> ExperimentPlan:
    """Cross the conditions with the plan's policy settings: `full` x {preserve, reinvent} becomes
    `full@preserve`, `full@reinvent`, each with the setting's transform.policy overrides."""
    if not plan.policies or any(c.policy for c in plan.conditions.values()):
        return plan
    crossed: dict[str, Condition] = {}
    for name, cond in plan.conditions.items():
        for pol in cond.policies or list(plan.policies):
            if pol not in plan.policies:
                raise ValueError(f"condition {name!r}: unknown policy setting {pol!r} (plan.policies: {list(plan.policies)})")
            ov = {f"transform.policy.{d}": v for d, v in policy_setting(plan.policies[pol]).items()}
            crossed[f"{name}@{pol}"] = cond.model_copy(update={"overrides": {**ov, **cond.overrides}, "base": name,
                                                                "policy": pol})
    return plan.model_copy(update={"conditions": crossed})


def _same_policy(plan: ExperimentPlan, name: str | None, condition: str) -> str | None:
    """A condition named in the judge settings (e.g. the quality baseline `flat`), under the same policy
    setting as `condition` when the plan crosses conditions with policies."""
    if not name or name in plan.conditions:
        return name
    pol = (plan.conditions.get(condition) or Condition()).policy
    return f"{name}@{pol}" if pol and f"{name}@{pol}" in plan.conditions else name


def load_plan(path: Path) -> tuple[ExperimentPlan, Path]:
    plan = materialise(ExperimentPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
    if plan.hypotheses == "default":
        from psalm_saga.experiments.hypotheses import default_hypotheses

        bases = {c.base or n: c.preset for n, c in plan.conditions.items()}
        plan = plan.model_copy(update={"hypotheses": default_hypotheses(bases, plan.policies, plan.margins)})
    elif isinstance(plan.hypotheses, str):
        raise ValueError(f"hypotheses: a list of tests or 'default', not {plan.hypotheses!r}")
    out = Path(plan.output) if plan.output else Path("experiments_out") / plan.name
    return plan, out if out.is_absolute() else (Path.cwd() / out)


def load_metadata(plan: ExperimentPlan, base: Path) -> dict[str, dict[str, str]]:
    if not plan.metadata:
        return {}
    path = Path(plan.metadata)
    path = path if path.is_absolute() else base / path
    if not path.exists():
        raise FileNotFoundError(f"metadata file not found: {path} (needed by the corpus-level analyses; remove "
                                "`metadata` from the plan to run without them)")
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        key = r.get("item") or (Path(r["file"]).stem if r.get("file") else None)
        if key:
            out[re.sub(r"[^\w.-]+", "_", key)[:80]] = r
    if plan.period_split:
        derive_period(out, **plan.period_split)
    return out


def derive_period(meta: dict[str, dict], at="median", name: str = "period", **kw) -> float | None:
    """Split the items into `early` and `late` at a value of a numeric column (default: its median),
    so that the split is fixed by rule rather than chosen after seeing the data."""
    col = kw.get("from", "year")
    vals = {}
    for k, r in meta.items():
        try:
            vals[k] = float(r.get(col))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    if at == "median":
        xs = sorted(vals.values())
        n = len(xs)
        cut = xs[(n - 1) // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    else:
        cut = float(at)
    for k, v in vals.items():
        meta[k][name] = "early" if v <= cut else "late"
    return cut


def expand(plan: ExperimentPlan, base: Path) -> list[Job]:
    items: list[tuple[str, Path, str]] = []
    for spec in plan.inputs:
        paths = sorted(Path(p) for p in glob.glob(str(base / spec.glob))) if spec.glob else [base / spec.path]
        items += [(_slug(p), p, spec.kind) for p in paths if p.is_file()]
    if plan.limit_items:
        items = items[: plan.limit_items]
    return [Job(i, p, k, c, m, r) for i, p, k in items for c, cond in plan.conditions.items() for m in plan.models
            for r in range(1, (cond.repeats or plan.repeats) + 1)]


_SKIP = {"copied_spans", "per_character", "name_leakage", "chapters_off_language"}


def _flatten(prefix: str, obj, out: dict) -> None:
    """Flatten evaluation.json into dotted columns; stylometric comparisons keep only rel_diff."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP:
                continue
            if k == "stylometrics" and isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and "rel_diff" in vv:
                        out[f"{prefix}{k}.{kk}.rel_diff"] = vv["rel_diff"]
                continue
            _flatten(f"{prefix}{k}.", v, out)
    elif isinstance(obj, int | float | bool | str) or obj is None:
        out[prefix.rstrip(".")] = obj


async def _run_job(job: Job, plan: ExperimentPlan, runs: Path, extra: list[str], log) -> dict:
    run_dir = runs / job.run_id
    cond = plan.conditions[job.condition]
    overrides = {**plan.overrides, **cond.overrides, **plan.models[job.model]}
    for o in extra:
        k, v = o.split("=", 1)
        overrides[k] = yaml.safe_load(v)
    t0 = time.monotonic()
    try:
        if (run_dir / "run.json").exists():
            p = Pipeline.open(run_dir)
            if p.store.meta().get("status") == "done":
                return {"job": job, "status": "done", "skipped": True}
        else:
            cfg = load_config(cond.preset, overrides)
            text = job.path.read_text(encoding="utf-8")
            kw = {"spec": json.loads(text)} if job.kind == "spec" else {job.kind: text}
            p = Pipeline.create(cfg, runs_dir=runs, run_id=job.run_id,
                                meta={"experiment": plan.name, "item": job.item, "condition": job.condition,
                                      "model_key": job.model, "repeat": job.repeat}, **kw)
        log(f"▶ {job.run_id}")
        await p.run()
        log(f"✓ {job.run_id} ({time.monotonic() - t0:.0f}s, ${p.llm.usage.cost_usd:.3f})")
        return {"job": job, "status": "done"}
    except Exception as exc:
        log(f"✗ {job.run_id}: {type(exc).__name__}: {str(exc)[:200]}")
        return {"job": job, "status": "failed", "error": str(exc)}


async def _judge(plan: ExperimentPlan, jobs: list[Job], runs: Path, out: Path, log,
                 metadata: dict[str, dict] | None = None) -> dict[str, dict]:
    if not plan.judge.model or not plan.judge.instruments:
        return {}
    cache = out / ".judge_cache"
    llm = judges.judge_llm(plan.judge.model, cache_dir=cache)
    tax = load_taxonomy("psalm")
    results: dict[str, dict] = {}
    path = out / "judgements.json"
    if path.exists():
        results = json.loads(path.read_text(encoding="utf-8"))
    by_id = {j.run_id: j for j in jobs}
    sem = asyncio.Semaphore(4)

    async def one(job: Job):
        rid = job.run_id
        store = RunStore(runs / rid)
        if store.meta().get("status") != "done" or not store.exists("story.md"):
            return
        res = results.setdefault(rid, {})
        story = "\n\n".join(json.loads(p.read_text(encoding="utf-8"))["text"] for p in store.glob("chapters/ch_*.json"))
        async with sem:
            if "spec_recovery" in plan.judge.instruments and "spec_recovery" not in res and store.exists("input/source.txt"):
                src_spec = _source_spec(job, jobs, runs)
                if src_spec is not None:
                    syn = await _extract_spec(store, story, runs / f".respec--{rid}", plan, job)
                    if syn is not None:
                        cfg = load_config(PipelineConfig_from(store))
                        res["spec_recovery"] = await judges.spec_recovery(llm, tax, src_spec, syn, cfg.transform.policy)
            if ("dimension_fidelity" in plan.judge.instruments and "dimension_fidelity" not in res
                    and store.exists("input/source.txt")):
                src = store.read_text("input/source.txt")
                if len(src.split()) <= plan.judge.dimension_fidelity_max_words:
                    res["dimension_fidelity"] = await judges.dimension_fidelity(llm, tax, src, story)
            base = _same_policy(plan, plan.judge.quality_baseline, job.condition)
            if "quality_pairwise" in plan.judge.instruments and base and job.condition != base and "quality" not in res:
                other = (by_id.get(f"{job.item}--{base}--{job.model}--r{job.repeat}")
                         or by_id.get(f"{job.item}--{base}--{job.model}--r1"))
                if other and RunStore(runs / other.run_id).exists("story.md"):
                    b_store = RunStore(runs / other.run_id)
                    b_story = "\n\n".join(json.loads(p.read_text(encoding="utf-8"))["text"] for p in b_store.glob("chapters/ch_*.json"))
                    res["quality"] = await judges.quality_pairwise(llm, story, b_story, seed=rid)
            if store.exists("input/source.txt"):
                src = store.read_text("input/source.txt")
                inst = plan.judge.instruments
                if "emotional_arc" in inst and "emotional_arc" not in res:
                    res["emotional_arc"] = await judges.emotional_arc(llm, src, story, k=plan.judge.arc_segments)
                if "surface_reuse" in inst and "surface_reuse" not in res:
                    from psalm_saga.text.chunking import split_chapters

                    syn_ch = [json.loads(p.read_text(encoding="utf-8"))["text"] for p in store.glob("chapters/ch_*.json")]
                    pol = PipelineConfig_from(store).transform.policy
                    res["surface_reuse"] = await judges.surface_reuse(
                        llm, [c.text for c in split_chapters(src)], syn_ch, pol, samples=plan.judge.reuse_samples)
                await _validity(plan, job, jobs, runs, store, res, src, story)
                if "reconstruction" in inst and "reconstruction" not in res:
                    md = (metadata or {}).get(job.item, {})
                    res["reconstruction"] = await judges.reconstruction(llm, src, story, title=md.get("title"),
                                                                        author=md.get("author"))
        path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"judging with {plan.judge.model}: {', '.join(plan.judge.instruments)}")
    await asyncio.gather(*(one(j) for j in jobs))
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


async def _validity(plan: ExperimentPlan, job: Job, jobs: list[Job], runs: Path, store: RunStore, res: dict,
                    src: str, story: str) -> None:
    """Second-judge agreement and lower anchors (psalm_saga/eval/validity.py)."""
    from psalm_saga.artifacts import Bible
    from psalm_saga.config import JudgesConfig
    from psalm_saga.eval.run_judges import psalm_judge
    from psalm_saga.eval.validity import JudgeContext

    inst = plan.judge.instruments
    ev = store.read_json("evaluation.json") if store.exists("evaluation.json") else {}
    own = ((ev.get("judges") or {}).get("psalm")) or None
    if own and "psalm_own" not in res:
        res["psalm_own"] = own
    pol = PipelineConfig_from(store).transform.policy
    tax = load_taxonomy("psalm")
    lang = ev.get("language", {}).get("expected") if isinstance(ev.get("language"), dict) else "en"
    src_bible, rec = store.maybe("bible_source.json", Bible), store.maybe("recovered/bible_source.json", Bible)
    if "psalm_check" in inst and own:
        checks = res.setdefault("psalm_checks", {})
        # a judge already on the run's own panel (judges.panel) is reused, not asked twice
        for pj in (ev.get("judges") or {}).get("panel") or []:
            if pj.get("model") in plan.judge.further_judges() and (pj.get("psalm") or {}).get("dimensions"):
                checks.setdefault(pj["model"], pj["psalm"])
        for model in plan.judge.further_judges():
            if model not in checks:
                llm2 = judges.judge_llm(model, cache_dir=runs.parent / ".judge_cache")
                checks[model] = await psalm_judge(JudgeContext(llm2, lang or "en"), tax, src, story, src_bible, rec, pol,
                                                  JudgesConfig())
        if not checks:
            res.pop("psalm_checks")
    if job.condition != _same_policy(plan, plan.judge.anchor_condition, job.condition) or job.repeat != 1:
        return
    # the next item of the same condition and model serves as the unrelated partner
    peers = [j for j in jobs if j.condition == job.condition and j.model == job.model and j.repeat == 1]
    other = peers[(peers.index(job) + 1) % len(peers)] if len(peers) > 1 else None
    if other is None:
        return
    o_store = RunStore(runs / other.run_id)
    if "psalm_anchor" in inst and "psalm_anchor" not in res and o_store.exists("input/source.txt"):
        llm = judges.judge_llm(plan.judge.model, cache_dir=runs.parent / ".judge_cache")
        res["psalm_anchor"] = await psalm_judge(JudgeContext(llm, lang or "en"), tax, src, o_store.read_text("input/source.txt"),
                                                src_bible, o_store.maybe("bible_source.json", Bible), pol, JudgesConfig())
        res["psalm_anchor"]["partner"] = other.item
    if "alignment_anchor" in inst and "alignment_anchor" not in res:
        design = store.maybe("bible.json", Bible)
        o_rec = o_store.maybe("recovered/bible_source.json", Bible)
        if design and o_rec:
            from psalm_saga.eval.kg_align import align_to_design
            from psalm_saga.graph import build_graph, compare_graphs
            from psalm_saga.pipeline import Pipeline

            ctx = Pipeline.open(store.root).context()
            chapters = {int(p.stem.split("_")[1]): json.loads(p.read_text(encoding="utf-8"))["text"]
                        for p in o_store.glob("chapters/ch_*.json")}
            al = await align_to_design(ctx, design, o_rec, chapters)
            cmp = compare_graphs(build_graph(design), build_graph(o_rec), {}, prealign=[(p["design"], p["text"]) for p in al["pairs"]],
                                 checks=al["checks"])
            ev_ = (cmp["summary"]["nodes"].get("event") or {})
            ca = (cmp["summary"]["edges"].get("causes") or {})
            res["alignment_anchor"] = {"partner": other.item, "events_recall": ev_.get("recall"),
                                       "causes_recall": ca.get("recall"), "stats": al["stats"]}


def PipelineConfig_from(store: RunStore):
    from psalm_saga.config import PipelineConfig

    return PipelineConfig.model_validate(store.meta()["config"])


def _source_spec(job: Job, jobs: list[Job], runs: Path) -> Spec | None:
    """The source spec extracted in this job, or by any job on the same item/model that has one."""
    for cand in [job, *[j for j in jobs if j.item == job.item and j.model == job.model]]:
        s = RunStore(runs / cand.run_id)
        if s.exists("spec_source.json"):
            spec = s.read_json("spec_source.json", Spec)
            if spec.dimensions:
                return spec
    return None


async def _extract_spec(store: RunStore, story: str, where: Path, plan: ExperimentPlan, job: Job) -> Spec | None:
    """Run the same extract+spec stages on the synthetic story (with the generating model)."""
    if (where / "spec_source.json").exists():
        return RunStore(where).read_json("spec_source.json", Spec)
    overrides = {**plan.overrides, **plan.models[job.model]}
    p = Pipeline.create("full", source=story, runs_dir=where.parent, run_id=where.name, overrides=overrides)
    try:
        await p.run(until="spec")
    except Exception:
        return None
    return p.store.maybe("spec_source.json", Spec)


def _collect(jobs: list[Job], runs: Path, judgements: dict) -> list[dict]:
    rows = []
    for j in jobs:
        store = RunStore(runs / j.run_id)
        meta = store.meta()
        row = {"run_id": j.run_id, "item": j.item, "condition": j.condition, "model": j.model, "repeat": j.repeat,
               "status": meta.get("status")}
        row.update(_usage_columns(meta))
        row["evaluation_guided_fixes"] = len(meta.get("evaluation_guided_fixes") or [])
        if store.exists("evaluation.json"):
            ev = store.read_json("evaluation.json")
            ev.pop("usage", None)
            ev.pop("timing", None)
            ev.pop("stylometrics", None)
            _flatten("", ev, row)
            # normalised scores (0–1, 1 = best) of every graded measure, and the mean per question
            for k, g in (ev.get("grades") or {}).items():
                if g.get("score") is not None:
                    row[f"score.{k}"] = g["score"]
                if g.get("value") is not None and g.get("grade"):
                    row[f"value.{k}"] = g["value"]
            row.update(psalm_columns((ev.get("judges") or {}).get("psalm")))
            for grp, v in (ev.get("summary_scores") or {}).items():
                row[f"question.{grp}"] = v
        jd = judgements.get(j.run_id, {})
        if "spec_recovery" in jd:
            row["judge.spec_recovery.mean"] = jd["spec_recovery"]["mean"]
            for k, v in jd["spec_recovery"]["by_dimension"].items():
                row[f"judge.spec_recovery.{k}"] = v["score"]
        for k, v in (jd.get("dimension_fidelity") or {}).items():
            row[f"judge.dimension_fidelity.{k}"] = v
        if "quality" in jd:
            row["judge.quality.win"] = {"condition": 1.0, "baseline": 0.0, "tie": 0.5}[jd["quality"]["winner"]]
        if "emotional_arc" in jd:
            row["judge.emotional_arc.pearson"] = jd["emotional_arc"].get("pearson")
            row["judge.emotional_arc.mean_abs_diff"] = jd["emotional_arc"].get("mean_abs_diff")
        if "surface_reuse" in jd:
            for k in ("per_1k", "close_paraphrase", "distinctive_particular"):
                row[f"judge.surface_reuse.{k}"] = jd["surface_reuse"].get(k)
        from psalm_saga.eval.validity import checks_of

        if checks_of(jd) and "psalm_own" in jd:
            from psalm_saga.eval.validity import krippendorff_alpha_units, psalm_units

            js = [jd["psalm_own"], *checks_of(jd).values()]
            row["validity.judge_alpha.function"] = krippendorff_alpha_units(psalm_units(js, "function_similarity"))
            row["validity.judge_alpha.expression"] = krippendorff_alpha_units(psalm_units(js, "expression_similarity"))
            from psalm_saga.eval.validity import mean_rating as _mr

            for fld, key in (("function_similarity", "function"), ("expression_similarity", "expression")):
                ms = [m for m in (_mr(j, fld) for j in js) if m is not None]
                row[f"validity.panel.{key}"] = round(sum(ms) / len(ms), 3) if ms else None
        if "psalm_anchor" in jd:
            from psalm_saga.eval.validity import mean_rating

            row["validity.anchor.function"] = mean_rating(jd["psalm_anchor"], "function_similarity")
            row["validity.anchor.expression"] = mean_rating(jd["psalm_anchor"], "expression_similarity")
        if "alignment_anchor" in jd:
            row["validity.anchor.events_recall"] = jd["alignment_anchor"].get("events_recall")
        if "reconstruction" in jd:
            for k in ("ngram5_gain", "longest_span", "identified", "author_identified"):
                if k in jd["reconstruction"]:
                    row[f"judge.reconstruction.{k}"] = jd["reconstruction"][k]
        rows.append(row)
    return rows


STORY_DIMS = ("character", "plot_structure", "scene_sequence", "world_building")
STYLE_DIMS = ("writing_style", "narrative_voice")


def psalm_columns(ps: dict | None) -> dict:
    """PSALM ratings (1–5) averaged over the story dimensions and over the style dimensions, and the share
    of ratings inside the range expected under each dimension's policy (eval/run_judges.py EXPECTED)."""
    from psalm_saga.eval.run_judges import EXPECTED

    out: dict = {}
    dims = (ps or {}).get("dimensions") or []
    if not dims:
        return out
    for group, keys in (("story", STORY_DIMS), ("style", STYLE_DIMS)):
        for field, name in (("function_similarity", "function"), ("expression_similarity", "expression")):
            v = [s[field] for d in dims if d.get("dimension") in keys for s in d.get("subdimensions") or []
                 if s.get(field) is not None]
            if v:
                out[f"psalm.{name}.{group}"] = round(statistics.fmean(v), 3)
    inside = total = 0
    for d in dims:
        ex = d.get("expected") or EXPECTED.get(d.get("policy") or "preserve")
        for s in d.get("subdimensions") or []:
            for field, key in (("function_similarity", "function"), ("expression_similarity", "expression")):
                if s.get(field) is not None:
                    total += 1
                    inside += ex[key][0] <= s[field] <= ex[key][1]
    if total:
        out["psalm.in_range"] = round(inside / total, 3)
    return out


USAGE_KEYS = ("calls", "cached_calls", "prompt_tokens", "completion_tokens", "cache_read_tokens", "cost_usd",
              "llm_seconds", "retries", "unpriced_calls")
STAGE_KEYS = ("wall_seconds", "cost_usd", "prompt_tokens", "completion_tokens", "calls")


def _usage_columns(meta: dict) -> dict:
    """Totals plus one column group per stage. Cost columns include cache replays as `*_first_run`."""
    u, t = meta.get("usage") or {}, meta.get("timing") or {}
    row = {f"usage.{k}": u.get(k) for k in USAGE_KEYS}
    row["usage.cost_usd_first_run"] = round((u.get("cost_usd") or 0) + (u.get("replayed_cost_usd") or 0), 6)
    row["timing.wall_seconds"] = t.get("wall_seconds", meta.get("seconds"))
    row["timing.invocations"] = t.get("invocations")
    stages = set(u.get("by_stage") or {}) | set(t.get("stages") or {})
    for st in sorted(stages):
        su, sw = (u.get("by_stage") or {}).get(st, {}), (t.get("stages") or {}).get(st, {})
        row[f"stage.{st}.wall_seconds"] = sw.get("wall_seconds")
        for k in ("cost_usd", "prompt_tokens", "completion_tokens", "calls"):
            row[f"stage.{st}.{k}"] = su.get(k)
    return row


from psalm_saga.eval.grading import CORE as _CORE  # noqa: E402
from psalm_saga.eval.grading import GROUPS as _GROUPS  # noqa: E402

# The report leads with the core measures as normalised scores (0–1, 1 = best) and one mean score per
# question; every other measure stays in results.csv as supporting detail.
CORE_SCORES = [f"score.{k}" for k in _CORE]
QUESTIONS = [f"question.{g}" for g in _GROUPS]
JUDGE_METRICS = ["judge.spec_recovery.mean", "judge.emotional_arc.pearson", "judge.surface_reuse.per_1k",
                 "judge.reconstruction.ngram5_gain", "judge.reconstruction.identified", "judge.quality.win"]
COST_METRICS = ["usage.cost_usd", "usage.cost_usd_first_run", "usage.prompt_tokens", "usage.completion_tokens",
                "timing.wall_seconds", "usage.llm_seconds"]
KEY_METRICS = [*QUESTIONS, *CORE_SCORES, *JUDGE_METRICS, *COST_METRICS]


def _summarise(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(f"{r['condition']} / {r['model']}", []).append(r)
    summary = {}
    for g, rs in groups.items():
        s = {"n": len(rs), "done": sum(r["status"] == "done" for r in rs)}
        for k in KEY_METRICS:
            vals = [float(r[k]) for r in rs if isinstance(r.get(k), int | float | bool) and r.get(k) is not None]
            if vals:
                s[k] = {"mean": round(statistics.fmean(vals), 4), "sd": round(statistics.pstdev(vals), 4), "n": len(vals)}
        stages: dict[str, dict] = {}
        for k in sorted({k for r in rs for k in r if k.startswith("stage.")}):
            _, st, metric = k.split(".", 2)
            vals = [float(r[k]) for r in rs if isinstance(r.get(k), int | float) and r.get(k) is not None]
            if vals:
                stages.setdefault(st, {})[metric] = round(statistics.fmean(vals), 4)
        s["stages"] = stages
        s["unpriced_calls"] = sum(int(r.get("usage.unpriced_calls") or 0) for r in rs)
        summary[g] = s
    return summary


def _records(rs: list[dict], runs: Path, metadata: dict[str, dict]) -> list:
    """One ItemRecord per finished run (original and synthetic side of every property)."""
    from psalm_saga.artifacts import Bible, TransformMap
    from psalm_saga.eval.corpus import ItemRecord
    from psalm_saga.eval.features import name_tokens, proper_noun_tokens, style_profile
    from psalm_saga.text.chunking import split_chapters

    out = []
    for r in rs:
        store = RunStore(runs / r["run_id"])
        if not store.exists("evaluation.json") or not store.exists("input/source.txt"):
            continue
        ev = store.read_json("evaluation.json")
        if not ev.get("features"):
            continue
        lang = store.meta().get("language") or "en"
        src = store.read_text("input/source.txt")
        syn_ch = [json.loads(p.read_text(encoding="utf-8"))["text"] for p in store.glob("chapters/ch_*.json")]
        syn = "\n\n".join(syn_ch)
        bible = store.maybe("bible_source.json", Bible) or Bible()
        mapping = (store.maybe("transform.json", TransformMap) or TransformMap()).as_dict()
        exclude = (name_tokens([*mapping, *mapping.values(), *(a for e in bible.entities for a in [e.name, *e.aliases])])
                   | proper_noun_tokens(src) | proper_noun_tokens(syn))

        def profiles(texts: list[str], lang=lang) -> list[dict]:
            return [style_profile(t, lang) for t in texts if len(t.split()) >= 200]

        out.append(ItemRecord(item=r["item"], features=ev["features"], source_text=src, synthetic_text=syn,
                              source_chapters=profiles([c.text for c in split_chapters(src)]),
                              synthetic_chapters=profiles(syn_ch), exclude=exclude,
                              metadata=metadata.get(r["item"], {})))
    return out


def _corpus(rows: list[dict], runs: Path, plan: ExperimentPlan, metadata: dict[str, dict]) -> dict:
    """Corpus-level validity (R1-R5, F1b) per condition / generator, on first repeats."""
    from psalm_saga.eval.corpus import corpus_report

    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r["status"] == "done" and r["repeat"] == 1:
            groups.setdefault(f"{r['condition']} / {r['model']}", []).append(r)
    return {g: corpus_report(_records(rs, runs, metadata), plan.analyses, plan.tstr_label) for g, rs in groups.items()}


def _report(plan: ExperimentPlan, summary: dict, replication: dict) -> str:
    lines = [f"# Experiment: {plan.name}", ""]

    def table(title: str, keys: list[str], note: str = "") -> None:
        cols = [k for k in keys if any(k in s for s in summary.values())]
        if not cols:
            return
        lines.extend([f"## {title}", ""] + ([note, ""] if note else []))
        lines.append("| condition / model | n | " + " | ".join(c.split(".", 1)[-1] for c in cols) + " |")
        lines.append("|---|---|" + "---|" * len(cols))
        for g, s in summary.items():
            cells = [f"{s[k]['mean']:.3g} ± {s[k]['sd']:.2g}" if k in s else "–" for k in cols]
            lines.append(f"| {g} | {s['done']}/{s['n']} | " + " | ".join(cells) + " |")
        lines.append("")

    table("Per question (mean score, 0–1, 1 = best)", QUESTIONS,
          "Mean of the core measures' normalised scores per question; see evaluation formulas in docs/EXPERIMENTS.md.")
    table("Core measures (normalised scores, mean ± sd)", CORE_SCORES)
    table("Experiment judges", JUDGE_METRICS)
    table("Cost and time (mean ± sd)", COST_METRICS)
    lines += ["", "## Cost and time per stage (mean per run)", "",
              "Wall-clock seconds include all attempts (resumes, retries); cost is what was actually spent.", ""]
    order = ["extract", "spec", "transform", "plan", "draft", "review", "repair", "guard", "agents_room", "edit", "judge"]
    for g, s in summary.items():
        st = s.get("stages") or {}
        if not st:
            continue
        names = sorted(st, key=lambda x: (order.index(x) if x in order else len(order), x))
        lines.append(f"**{g}**" + (f" — {s['unpriced_calls']} calls had no known price (counted as $0)" if s.get("unpriced_calls") else ""))
        lines.append("")
        lines.append("| stage | wall s | $ | input tok | output tok | calls |")
        lines.append("|---|---|---|---|---|---|")
        for n in names:
            v = st[n]
            fmt = lambda x, f: "–" if x is None else format(x, f)  # noqa: E731
            lines.append(f"| {n} | {fmt(v.get('wall_seconds'), '.1f')} | {fmt(v.get('cost_usd'), '.4f')} | "
                         f"{fmt(v.get('prompt_tokens'), ',.0f')} | {fmt(v.get('completion_tokens'), ',.0f')} | {fmt(v.get('calls'), '.1f')} |")
        lines.append("")
    lines += _corpus_lines(replication)
    return "\n".join(lines) + "\n"


def _fmt(x, f=".2f") -> str:
    return "–" if x is None else format(x, f)


def _ci_str(ci) -> str:
    return f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""


def _corpus_lines(corpus: dict) -> list[str]:
    lines = ["", "## Corpus-level validity", "",
             "R1: Spearman ρ between original and synthetic values across items (95% bootstrap CI). "
             "R2: sd(synthetic) / sd(original) across items; < 1 means the synthetic corpus is more homogeneous.", ""]
    feats = sorted({f for g in corpus.values() for f in (g.get("R1_rank_agreement") or {})})
    if feats:
        lines.append("| property | " + " | ".join(f"{g} R1 | R2" for g in corpus) + " |")
        lines.append("|---|" + "---|---|" * len(corpus))
        for f in feats:
            cells = []
            for g in corpus.values():
                r1 = (g.get("R1_rank_agreement") or {}).get(f) or {}
                r2 = (g.get("R2_dispersion") or {}).get(f) or {}
                cells += [_fmt(r1.get("spearman")) + _ci_str(r1.get("ci95")), _fmt(r2.get("ratio"))]
            lines.append(f"| {f} | " + " | ".join(cells) + " |")
    lines += ["", "| condition / model | items | F1b top-1 (chance) | F1b mean rank | R4 pMSE ratio | R4 CV accuracy |",
              "|---|---|---|---|---|---|"]
    for g, c in corpus.items():
        d, r4 = c.get("F1b_cosine_delta") or {}, c.get("R4_distinguishability") or {}
        lines.append(f"| {g} | {c.get('items')} | {_fmt(d.get('top1_accuracy'))} ({_fmt(d.get('chance'))}) | "
                     f"{_fmt(d.get('mean_rank'))} | {_fmt(r4.get('pmse_ratio'))} | {_fmt(r4.get('cv_accuracy'))} |")
    rep = [(g, a) for g, c in corpus.items() for a in c.get("R3_replication") or []]
    if rep:
        lines += ["", "**R3 analysis replication** (estimate [95% CI] on originals vs synthetic)", "",
                  "| condition / model | analysis | original | synthetic | sign agrees | synthetic in original CI |",
                  "|---|---|---|---|---|---|"]
        for g, a in rep:
            if "error" in a:
                lines.append(f"| {g} | {a.get('feature')} | {a['error']} | | | |")
                continue
            lines.append(f"| {g} | {a['analysis']} | {_fmt(a['source']['estimate'], '.3f')}{_ci_str(a['source']['ci95'])} | "
                         f"{_fmt(a['synthetic']['estimate'], '.3f')}{_ci_str(a['synthetic']['ci95'])} | "
                         f"{a.get('sign_agrees', '–')} | {a.get('synthetic_within_source_ci', '–')} |")
    tr = [(g, c["R5_classifier_transfer"]) for g, c in corpus.items() if c.get("R5_classifier_transfer")]
    if tr:
        lines += ["", "**R5 classifier transfer** (chapter-level, leave one book out)", "",
                  "| condition / model | label | TSTR | TRTR | majority | TSTR/TRTR |", "|---|---|---|---|---|---|"]
        for g, t in tr:
            lines.append(f"| {g} | {t['label']} | {_fmt(t.get('tstr_accuracy'))} | {_fmt(t.get('trtr_accuracy'))} | "
                         f"{_fmt(t.get('majority_accuracy'))} | {_fmt(t.get('tstr_over_trtr'))} |"
                         + (f" {t['error']}" if t.get("error") else ""))
    return lines


async def run_experiment(plan_path: Path, *, dry_run: bool = False, extra_overrides: list[str] | None = None,
                         judge: bool = True, console=None) -> dict:
    plan, out = load_plan(plan_path)
    jobs = expand(plan, plan_path.parent)
    log = (console.print if console else print)
    log(f"{plan.name}: {len(jobs)} jobs = {len({j.item for j in jobs})} items × {len(plan.conditions)} conditions × "
        f"{len(plan.models)} models, {plan.repeats} sample(s) per item unless a condition sets its own → {out}")
    if dry_run:
        for j in jobs:
            log(f"  {j.run_id}  [{plan.conditions[j.condition].preset}]  {j.path}")
        return {"jobs": len(jobs)}
    metadata = load_metadata(plan, plan_path.parent)  # fail before spending anything if it is missing
    runs = out / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (out / "plan.yaml").write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")
    sem = asyncio.Semaphore(max(1, plan.concurrency))

    async def guarded(j):
        async with sem:
            return await _run_job(j, plan, runs, extra_overrides or [], log)

    results = await asyncio.gather(*(guarded(j) for j in jobs))
    judgements = await _judge(plan, jobs, runs, out, log, metadata) if judge else {}
    rows = _collect(jobs, runs, judgements)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("run_id", "item", "condition", "model", "repeat", "status"), k))
    with open(out / "results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    summary = _summarise(rows)
    replication = _corpus(rows, runs, plan, metadata)
    if judgements:
        from psalm_saga.eval.validity import summarise as _validity_summary

        replication["validity"] = _validity_summary(judgements)
    from psalm_saga.experiments.hypotheses import evaluate as _hypotheses
    from psalm_saga.experiments.hypotheses import report_lines

    tests = _hypotheses(rows, plan.hypotheses, alpha=plan.alpha, B=plan.bootstrap) if plan.hypotheses else None
    (out / "summary.json").write_text(json.dumps({"name": plan.name, "jobs": len(jobs),
                                                  "failed": sum(r["status"] == "failed" for r in results),
                                                  "summary": summary, "corpus": replication, "hypotheses": tests},
                                                 indent=1), encoding="utf-8")
    (out / "report.md").write_text(_report(plan, summary, replication) + "\n".join(report_lines(tests)) + "\n",
                                   encoding="utf-8")
    from psalm_saga.experiments.report_html import render

    (out / "report.html").write_text(render(plan.name, replication), encoding="utf-8")
    log(f"results → {out / 'results.csv'}, {out / 'report.md'}, {out / 'report.html'}")
    return {"jobs": len(jobs), "summary": summary}
