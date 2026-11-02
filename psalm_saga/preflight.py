"""Pre-flight check: find configuration problems before a run spends time and money.

A run that fails halfway because a model name is misspelt or a key is missing has already paid for
the analysis. The check runs before the first stage (and before every resume) and covers what can
go wrong in the settings:

  static   stage implementations exist; policies, priorities and limits are valid values; the
           input is there; the judge is a different model from the writer (a warning)
  keys     every model's provider has its API key (or endpoint) set, in the environment or among
           the keys saved on this machine
  live     one tiny call per distinct model the remaining stages will use ("reply with OK"): wrong
           model names, revoked keys, unreachable endpoints and missing permissions show up here

Problems are `error` (the run would fail: it is not started, its status becomes needs_attention
and the settings can be changed before starting again) or `warning` (shown, not blocking). The
result is written to preflight.json in the run folder.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass

from psalm_saga.config import ModelConfig, PipelineConfig


@dataclass
class Problem:
    severity: str  # error | warning
    where: str  # the setting concerned, e.g. "models.default" or "stages.draft.impl"
    message: str
    hint: str = ""


class PreflightFailed(RuntimeError):
    def __init__(self, report: dict):
        self.report = report
        errs = [p for p in report["problems"] if p["severity"] == "error"]
        super().__init__("; ".join(f"{p['where']}: {p['message']}" for p in errs)[:1500])


def _provider(name: str) -> str | None:
    if "/" in name:
        return name.split("/", 1)[0]
    try:
        import litellm

        return litellm.get_llm_provider(name)[1]
    except Exception:
        return None


def roles_needed(config: PipelineConfig, stages: list[str]) -> dict[str, str]:
    """Model role per stage that will run (the stage's own model setting, else its name)."""
    out = {}
    for name in stages:
        sc = config.stages.get(name)
        if sc is None or not sc.enabled:
            continue
        out[name] = sc.model or name
        if name == "review":
            out["review (re-planning)"] = "plan"
        if name == "recover":
            ex = config.stages.get("extract")
            out["recover"] = (ex.model if ex and ex.model else "extract")
    if "evaluate" in stages and config.judges.enabled:
        out["evaluate (judges)"] = "judge"
        for i, _ in enumerate(config.judges.panel, 2):
            out[f"evaluate (judge {i})"] = f"judge_{i}"
    return out


def _judge_model(config: PipelineConfig) -> ModelConfig:
    base = config.model_for("judge")
    if config.judges.model:
        return ModelConfig(**{**base.model_dump(), "name": config.judges.model})
    return base


def workload(config: PipelineConfig, stages: list[str]) -> dict | None:
    """Worst-case number of full-chapter rewrites per chapter for the stages still to run."""
    from psalm_saga.priorities import steered_params

    def params(name):
        sc = config.stages.get(name)
        return steered_params(config.priorities, name, dict(sc.params)) if sc and sc.enabled and name in stages else None

    d, c, r = params("draft"), params("conform"), params("review")
    if d is None:
        return None
    cr = int(c.get("rounds", 2)) if c is not None else 0
    parts, n = ["draft 1"], 1
    if cr:
        parts.append(f"conform {cr}")
        n += cr
    passes = 1
    if r is not None:
        rv = (1 + cr if r.get("replan", True) else 0) + int(r.get("rounds", 1)) + (min(cr, int(r.get("restyle_rounds", 2))) if cr else 0)
        parts.append(f"review {rv}")
        n += rv
        passes += int(r.get("max_backtracks", 1))
    detail = " + ".join(parts) + (f", x{passes} with going back to planning" if passes > 1 else "")
    return {"per_pass": n, "passes": passes, "worst": n * passes, "detail": detail}


def static_checks(config: PipelineConfig, *, stages: list[str], has_input: bool = True) -> list[Problem]:
    from psalm_saga.priorities import groups
    from psalm_saga.stages import get_stage

    out: list[Problem] = []
    for name, sc in config.stages.items():
        if not sc.enabled:
            continue
        try:
            get_stage(name, sc.impl or {"draft": "chapter"}.get(name))
        except ValueError as exc:
            out.append(Problem("error", f"stages.{name}.impl", str(exc), "Choose one of the implementations listed."))
        if sc.model and sc.model not in config.models:
            out.append(Problem("warning", f"stages.{name}.model",
                               f"model role {sc.model!r} is not defined under models; the default model is used",
                               f"Add models.{sc.model} or clear the setting."))
    for dim, pol in (config.transform.policy or {}).items():
        if pol not in ("preserve", "abstract", "regenerate"):
            out.append(Problem("error", f"transform.policy.{dim}", f"unknown policy {pol!r}",
                               "Use preserve, abstract or regenerate."))
    known = set(groups()) | {k for v in groups().values() for k in v}
    for p in config.priorities:
        if p not in known:
            out.append(Problem("error", "priorities", f"unknown measure or group {p!r}",
                               "Use a measure key or one of: " + ", ".join(sorted(groups()))))
    if config.limits.max_cost_usd is not None and config.limits.max_cost_usd <= 0:
        out.append(Problem("error", "limits.max_cost_usd", "the budget is zero or negative", "Raise it or clear it."))
    if config.limits.max_minutes is not None and config.limits.max_minutes <= 0:
        out.append(Problem("error", "limits.max_minutes", "the time limit is zero or negative", "Raise it or clear it."))
    if not has_input:
        out.append(Problem("error", "input", "the run has no source text, premise or spec"))
    w = workload(config, stages)
    effort = (config.model_for("draft").extra or {}).get("reasoning_effort")
    if w and (w["worst"] >= 20 or (effort in ("high", "xhigh", "max") and w["worst"] >= 12)):
        out.append(Problem("warning", "workload",
                           f"each chapter may be rewritten up to {w['worst']} times ({w['detail']}); usually far fewer"
                           + (f". With reasoning effort {effort!r}, one rewrite of a long chapter can take minutes" if effort else ""),
                           "To bound the run: set limits.max_minutes (the run stops and can be continued), "
                           "stages.review.params.max_backtracks=0 (no second pass), or fewer stages.conform.params.rounds."))
    if config.judges.enabled and "evaluate" in stages:
        jm, wm = _judge_model(config).name, config.model_for("draft").name
        if jm == wm and not jm.startswith("fake/"):
            out.append(Problem("warning", "judges.model", f"the judge is the writer's own model ({jm})",
                               "A judge from another model family is less likely to be lenient toward its own text."))
        seen = {jm}
        for i, entry in enumerate(config.judges.panel):
            name = entry if isinstance(entry, str) else (entry or {}).get("name")
            if not name:
                out.append(Problem("error", f"judges.panel[{i}]", "a panel judge has no model name",
                                   "Give a model id, or {name: <id>, api_base: <url>}."))
                continue
            if name == wm and not name.startswith("fake/"):
                out.append(Problem("warning", f"judges.panel[{i}]", f"this judge is the writer's own model ({name})",
                                   "Use a model of another family."))
            if name in seen:
                out.append(Problem("warning", f"judges.panel[{i}]", f"{name} is already a judge of this run",
                                   "Each judge should be a different model."))
            seen.add(name)
    return out


def key_checks(models: dict[str, ModelConfig]) -> list[Problem]:
    from psalm_saga import keys

    out: list[Problem] = []
    seen = set()
    for where, mc in models.items():
        if mc.name.startswith("fake/") or mc.name in seen:
            continue
        seen.add(mc.name)
        prov = _provider(mc.name)
        try:
            import litellm

            known = {str(getattr(x, "value", x)) for x in litellm.provider_list}
        except Exception:
            known = set()
        if prov is not None and known and prov not in known:
            out.append(Problem("error", where, f"{prov!r} is not a provider LiteLLM knows (model {mc.name!r})",
                               "Write the model as provider/model, e.g. openai/gpt-5.5, anthropic/claude-sonnet-5-5, "
                               "mistral/mistral-large-latest, openrouter/<vendor>/<model> or ollama/<model>."))
            continue
        if prov is None:
            out.append(Problem("error", where, f"cannot tell which provider serves {mc.name!r}",
                               "Write the model as provider/model, e.g. openai/gpt-5.5 or anthropic/claude-sonnet-5-5."))
            continue
        spec = keys.PROVIDERS.get(prov)
        if not spec or prov == "ollama":  # no table, or a local server with a default address
            continue  # a provider we have no key table for: the live call will tell
        needed = [v for v, kind in spec["vars"].items() if kind in ("key", "url")]
        if prov in ("openai", "vllm"):
            needed = [v for v in needed if spec["vars"][v] == "key"] if prov == "openai" else needed[:1]
        if any(k in (mc.extra or {}) for k in ("api_key", "api_base", "base_url")):
            continue
        if not any(os.environ.get(v) for v in needed):
            out.append(Problem("error", where, f"no {' / '.join(needed)} is set for {spec['label']} ({mc.name})",
                               "Add the key under API keys (stored on this machine) or set it in the environment."))
    return out


async def live_checks(config: PipelineConfig, models: dict[str, ModelConfig], timeout_s: float = 90) -> tuple[list[Problem], list[dict]]:
    from psalm_saga.llm import LLM, Part
    from psalm_saga.llm.limiter import LimiterRegistry

    distinct: dict[str, tuple[str, ModelConfig]] = {}
    for where, mc in models.items():
        distinct.setdefault(mc.name, (where, mc))
    probe_cfg = config.model_copy(deep=True)
    probe_cfg.cache = False
    probe_cfg.limits.max_cost_usd = None
    results: list[dict] = []
    problems: list[Problem] = []

    async def one(name: str, where: str, mc: ModelConfig):
        role = f"__probe_{len(probe_cfg.models)}"
        probe_cfg.models[role] = mc.model_copy(update={"max_retries": 1, "timeout_s": min(mc.timeout_s, timeout_s),
                                                       "stream": False})
        llm = LLM(probe_cfg, cache_dir=None, limiters=LimiterRegistry())
        t0 = time.monotonic()
        try:
            text = await asyncio.wait_for(llm.text(role, "You are a connectivity check.",
                                                   [Part("Reply with the single word OK.")], max_tokens=16, tag="preflight"),
                                          timeout=timeout_s)
            results.append({"model": name, "used_by": where, "ok": True, "seconds": round(time.monotonic() - t0, 2),
                            "reply": text[:40], "cost_usd": round(llm.usage.cost_usd, 6)})
        except Exception as exc:
            msg = str(exc)
            low = msg.lower()
            hint = ("Check the model name (provider/model) and that your account has access to it."
                    if any(w in low for w in ("not found", "does not exist", "notfound", "unknown model", "invalid model"))
                    else "Check the API key." if any(w in low for w in ("auth", "api key", "401", "permission", "403"))
                    else "Check the endpoint address and your network." if any(w in low for w in ("connect", "timeout", "resolve"))
                    else "")
            results.append({"model": name, "used_by": where, "ok": False, "seconds": round(time.monotonic() - t0, 2),
                            "error": msg[:600]})
            problems.append(Problem("error", where, f"{name} did not answer: {msg[:400]}", hint))

    await asyncio.gather(*(one(n, w, mc) for n, (w, mc) in distinct.items()))
    return problems, results


async def preflight(config: PipelineConfig, *, stages: list[str], has_input: bool = True, live: bool = True) -> dict:
    """Check the settings for the given stages. Returns {"ok", "problems", "models", "checked_at"}."""
    problems = static_checks(config, stages=stages, has_input=has_input)
    roles = roles_needed(config, stages)
    models: dict[str, ModelConfig] = {}
    for stage, role in roles.items():
        if role.startswith("judge_"):
            i = int(role.split("_")[1])
            entry = config.judges.panel[i - 2]
            spec = {"name": entry} if isinstance(entry, str) else dict(entry)
            base = _judge_model(config)
            mc = ModelConfig(**{**base.model_dump(), "name": spec.pop("name"),
                                "extra": {**{k: v for k, v in base.extra.items() if k != "api_base"}, **spec}})
            models[f"judges.panel[{i - 2}] (for {stage})"] = mc
            continue
        mc = _judge_model(config) if role == "judge" else config.model_for(role)
        key = "models." + (role if role in config.models else "default") if role != "judge" else (
            "judges.model" if config.judges.model else "models." + ("judge" if "judge" in config.models else "default"))
        models[f"{key} (for {stage})"] = mc
    by_setting: dict[str, ModelConfig] = {}
    for where, mc in models.items():
        by_setting.setdefault(where.split(" (for")[0], mc)
    problems += key_checks(by_setting)
    results: list[dict] = []
    if live and not any(p.severity == "error" for p in problems):
        lp, results = await live_checks(config, by_setting)
        problems += lp
    return {"ok": not any(p.severity == "error" for p in problems), "problems": [asdict(p) for p in problems],
            "models": results, "roles": roles, "checked_at": time.time()}
