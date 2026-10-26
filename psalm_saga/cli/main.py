"""`saga` command line.

    saga run book.txt                         # source -> synthetic counterpart (preset: full)
    saga run premise.md --as premise --set length.target_words=2500
    saga run book.txt -p no_review --model openai/gpt-5.5 --set stages.guard.params.min_span=8
    saga resume runs/<id> --from plan         # redo planning onward after editing spec.json
    saga chat [runs/<id>]                     # interactive session (slash commands + free-text edits)
    saga experiment experiments/pilot.yaml    # grid of inputs x conditions x models
    saga serve                                # web app
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from psalm_saga.config import load_config, preset_names
from psalm_saga.sdk import EDITABLE, Run, Saga

app = typer.Typer(add_completion=False, no_args_is_help=True, help="PSALM-SAGA: dimension-controlled story synthesis.")


@app.callback()
def _startup() -> None:
    """Load the user's saved API keys (saga keys) before any command runs."""
    from psalm_saga import keys

    keys.load()


@app.command("keys")
def keys_cmd(action: str = typer.Argument("list", help="list | set | unset"),
             var: str = typer.Argument("", help="e.g. OPENAI_API_KEY (see `saga keys list`)")):
    """API keys and endpoints, kept in your settings folder (never in run folders)."""
    from psalm_saga import keys

    if action == "list":
        for p in keys.status():
            console.print(f"[bold]{p['label']}[/bold]  [dim]{p['example']}[/dim]")
            for r in p["vars"]:
                console.print(f"   {r['var']:<22} {r['display'] or '[dim]not set[/dim]'}  [dim]{r['source']}[/dim]")
        console.print(f"[dim]saved in {keys.path()}[/dim]")
    elif action in ("set", "unset"):
        if not var:
            raise typer.BadParameter("name the variable, e.g. `saga keys set OPENAI_API_KEY`")
        value = typer.prompt(var, hide_input=keys.known_vars().get(var) == "key") if action == "set" else ""
        keys.set_value(var, value)
        console.print(f"{var} {'saved' if value else 'removed'} ({keys.path()})")
    else:
        raise typer.BadParameter("action must be list, set or unset")
console = Console()


# ---------------------------------------------------------------- progress rendering


class Progress:
    """Compact live log of pipeline events."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.calls = 0
        self.tokens = 0
        self.cost = 0.0

    def __call__(self, e: dict) -> None:
        t = e.get("type")
        if t == "llm_call":
            self.calls += 1
            self.tokens += e.get("prompt_tokens", 0) + e.get("completion_tokens", 0)
            self.cost += e.get("cost_usd", 0) or 0
            if self.verbose:
                took = "(cached)" if e.get("cached") else f"{e.get('seconds')}s"
                console.print(f"  [dim]· {e.get('tag')} {e.get('model')} {took}[/]")
        elif t == "stage_started":
            console.print(f"[bold cyan]▶ {e['stage']}[/] [dim]({e.get('impl')})[/]")
        elif t == "stage_finished":
            console.print(f"[green]✓ {e['stage']}[/] [dim]{e['seconds']}s · {self.calls} calls · {self.tokens:,} tok · ${self.cost:.3f}[/]")
        elif t == "stage_skipped":
            console.print(f"[dim]↷ {e['stage']} (done)[/]")
        elif t == "stage_progress" and (e.get("message") or self.verbose):
            msg = e.get("message") or f"{e.get('done')}/{e.get('total')}"
            console.print(f"  [dim]{e['stage']}: {msg}[/]")
        elif t == "llm_retry":
            console.print(f"  [yellow]↻ {e.get('tag')}: retry {e['attempt']} in {e['wait_s']}s — {e['error'][:120]}[/]")
        elif t in ("warning", "language_mismatch", "variety_mismatch"):
            console.print(f"  [yellow]! {e.get('message') or e}[/]")
        elif t == "run_failed":
            console.print(f"[red]✗ {e['error']}[/]")


def _overrides(set_: list[str], model: str | None, lang: str | None, words: int | None, chapters: str | None) -> list[str]:
    out = list(set_ or [])
    if model:
        out.append(f"models.default.name={model}")
    if lang:
        out.append(f"language.output={lang}")
    if words:
        out.append(f"length.target_words={words}")
    if chapters:
        out.append(f"length.chapters={chapters}")
    return out


def _read_input(path: str, as_: str) -> dict:
    p = Path(path)
    text = sys.stdin.read() if path == "-" else (p.read_text(encoding="utf-8") if p.exists() else path)
    kind = as_
    if kind == "auto":
        if p.suffix in (".json", ".yaml", ".yml"):
            kind = "spec"
        else:
            kind = "premise" if len(text.split()) < 400 else "source"
    if kind == "spec":
        data = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
        return {"spec": data}
    return {kind: text}


def _dur(s) -> str:
    if s is None:
        return "–"
    s = float(s)
    return f"{s:.1f}s" if s < 120 else f"{int(s // 60)}m{int(s % 60):02d}s"


def usage_table(st: dict) -> Table:
    """Per-stage wall-clock time, tokens and cost (cumulative over all invocations of the run)."""
    by = (st.get("usage") or {}).get("by_stage") or {}
    tim = (st.get("timing") or {}).get("stages") or {}
    t = Table("stage", "wall", "runs", "calls", "input tok", "output tok", "$", "retries", title="per stage", title_justify="left")
    names = [x["name"] for x in st["stages"] if x["name"] in by or x["name"] in tim] + [n for n in by if n not in {x["name"] for x in st["stages"]}]
    for n in names:
        b, w = by.get(n, {}), tim.get(n, {})
        t.add_row(n, _dur(w.get("wall_seconds")), str(w.get("runs", "–")), str(int(b.get("calls", 0))),
                  f"{int(b.get('prompt_tokens', 0)):,}", f"{int(b.get('completion_tokens', 0)):,}",
                  f"{b.get('cost_usd', 0):.4f}", str(int(b.get("retries", 0))))
    return t


def _summary(run: Run) -> None:
    ev = run.evaluation
    st = run.status()
    t = Table(title=f"run {run.id}", show_header=False, box=None)
    t.add_row("status", str(st.get("status")))
    if ev:
        t.add_row("language", f"{ev.get('language', {}).get('expected')} (detected {ev.get('language', {}).get('detected')})")
        ln = ev.get("length", {})
        t.add_row("length", f"{ln.get('words')} words / target {ln.get('target')} · {ln.get('chapters')} chapters")
    if "fidelity" in ev:
        f = ev["fidelity"]
        t.add_row("structure", f"chapters equal: {f['chapter_count']['equal']} · scenes match: {f.get('scenes_per_chapter_match')}")
        t.add_row("style drift", f"{f.get('stylometric_mean_rel_diff')} (mean rel. diff, 0 = identical)")
        ch = f.get("characters", {})
        t.add_row("characters", f"salience ρ {ch.get('salience_spearman')} · co-occurrence J {ch.get('cooccurrence_jaccard')}")
    va = ev.get("variety") or {}
    if va.get("applicable"):
        t.add_row("variety", f"{va['source_variety']} · source {va['source_share']} → synthetic {va['synthetic_share']} (retention {va.get('retention')}, {va['target']})")
    if "leakage" in ev:
        lk = ev["leakage"]
        t.add_row("leakage", f"8-gram {lk['ngram8_overlap']:.4f} · longest span {lk['longest_copied_span_words']} words · names {lk['name_leakage'] or 'none'}")
    u = st.get("usage") or {}
    tm = st.get("timing") or {}
    t.add_row("usage", f"{u.get('calls', 0)} calls ({u.get('cached_calls', 0)} cached) · {u.get('prompt_tokens', 0):,} in / {u.get('completion_tokens', 0):,} out · ${u.get('cost_usd', 0):.3f} · {u.get('retries', 0)} retries")
    t.add_row("time", f"{_dur(tm.get('wall_seconds'))} wall clock over {tm.get('invocations', 1)} invocation(s) · {_dur(u.get('llm_seconds'))} model time")
    if u.get("unpriced_calls"):
        t.add_row("note", f"[yellow]{u['unpriced_calls']} calls had no known price (counted as $0); set models.<role>.input_cost_per_mtok / output_cost_per_mtok[/]")
    console.print(t)
    console.print(usage_table(st))
    t = Table(show_header=False, box=None)
    t.add_row("output", str(run.path / ("story.md" if run.story else "")))
    console.print(t)


# ---------------------------------------------------------------- commands


@app.command()
def run(
    input: str = typer.Argument(..., help="Source text file, premise file, spec .json, inline text, or '-' for stdin."),
    preset: str = typer.Option("full", "--preset", "-p", help=f"One of: {', '.join(preset_names())}, or a YAML path."),
    as_: str = typer.Option("auto", "--as", help="auto | source | premise | spec"),
    set_: list[str] = typer.Option([], "--set", "-s", help="Config override key=value (repeatable)."),
    model: str = typer.Option(None, "--model", "-m", help="Default model (LiteLLM id, e.g. anthropic/claude-sonnet-5-5)."),
    lang: str = typer.Option(None, "--lang", help="Output language (ISO 639-1). Default: same as input."),
    variety: str = typer.Option(None, "--variety", help="Language variety: auto (keep the source's dialect/spelling), modern, or a description."),
    words: int = typer.Option(None, "--words", help="Target length in words. Default: match the source."),
    chapters: str = typer.Option(None, "--chapters", help="Chapter count, 'auto' or 'match'."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    run_id: str = typer.Option(None, "--id"),
    until: str = typer.Option(None, "--until", help="Stop after this stage (e.g. spec, to review it first)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run a pipeline on a new input."""
    ov = _overrides(set_, model, lang, words, chapters) + ([f"language.variety={variety}"] if variety else [])
    saga = Saga(preset, overrides=ov, runs_dir=runs_dir, on_event=Progress(verbose))
    r = saga.create(run_id=run_id, **_read_input(input, as_))
    console.print(f"[bold]run[/] {r.path}  [dim]preset={saga.config.name} mode={r.pipeline.mode} lang={r.pipeline.language()}[/]")
    r.run(until=until)
    _summary(r)


@app.command()
def resume(
    run_dir: Path,
    from_: str = typer.Option(None, "--from", help="Invalidate and redo this stage and everything after it."),
    set_: list[str] = typer.Option([], "--set", "-s"),
    until: str = typer.Option(None, "--until"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Continue an interrupted run (finished chunks/chapters are kept) or redo from a stage."""
    r = Saga.open(run_dir, overrides=set_ or None, on_event=Progress(verbose))
    r.run(rerun_from=from_, until=until)
    _summary(r)


@app.command()
def status(run_dir: Path):
    """Stage-by-stage status of a run."""
    r = Saga.open(run_dir)
    st = r.status()
    t = Table("stage", "impl", "applies", "done")
    for s in st["stages"]:
        t.add_row(s["name"], s["impl"], "yes" if s["applies"] else "-", "✓" if s["done"] else "")
    console.print(f"{st['run']} · {st.get('status')} · mode {st['mode']} · {st['language']}")
    console.print(t)
    console.print(usage_table(st))
    if st.get("error"):
        console.print(f"[red]{st['error']}[/]")


@app.command()
def show(run_dir: Path, artifact: str = typer.Argument("story", help="story | spec | spec_source | bible | plan | transform | evaluation | chapter:N | events")):
    """Print an artifact."""
    r = Saga.open(run_dir)
    if artifact == "story":
        console.print(Markdown(r.story or "(no story yet)"))
    elif artifact in ("spec", "spec_source") and r.artifact(artifact):
        console.print(Markdown(r.artifact(artifact).render()))
    elif artifact == "events":
        for e in r.store.events()[-50:]:
            console.print(json.dumps(e, ensure_ascii=False)[:200])
    else:
        a = r.artifact(artifact)
        if a is None:
            raise typer.BadParameter(f"No artifact {artifact!r} in this run")
        console.print_json(a.model_dump_json() if hasattr(a, "model_dump_json") else json.dumps(a, ensure_ascii=False))


@app.command()
def edit(run_dir: Path, artifact: str, instruction: str, then_run: bool = typer.Option(False, "--run")):
    """Edit an artifact with a natural-language instruction (downstream stages are invalidated)."""
    r = Saga.open(run_dir, on_event=Progress())
    r.edit(artifact, instruction)
    console.print(f"[green]updated {artifact}[/]; downstream stages will be regenerated.")
    if then_run:
        r.run()
        _summary(r)


@app.command()
def export(
    run_dir: Path,
    release: bool = typer.Option(False, "--release", help="Synthetic material only (no source text or source-derived files)."),
    out: Path = typer.Option(None, "--out", "-o"),
):
    """Zip a run for sharing or re-evaluation (full by default: includes the source text)."""
    path = Saga.open(run_dir).export(out, release=release)
    console.print(f"{'release' if release else 'full'} bundle → {path}")
    if not release:
        console.print("[yellow]Contains the source text: internal use only.[/]")


@app.command()
def graph(
    run_dir: Path,
    source: bool = typer.Option(False, "--source", help="Graph of the source instead of the synthetic story."),
    fmt: str = typer.Option("graphml", "--format", "-f", help="graphml (Gephi, yEd, Cytoscape, networkx) or json"),
    out: Path = typer.Option(None, "--out", "-o", help="Output file (default: <run>/graph-<which>.<ext>)"),
    compare: str = typer.Option(None, "--compare", help="design | text: the source graph aligned with the synthetic "
                                "design, or with a graph re-extracted from the synthetic text (one extraction pass)."),
):
    """Export the story knowledge graph (characters, places, scenes, events and their relations)."""
    from psalm_saga.graph import to_graphml

    run = Saga.open(run_dir)
    if compare:
        if compare == "text":
            run.recover()
        which, g = f"compare-{compare}", run.graph("compare", against=compare)
    else:
        which = "source" if source else "synthetic"
        g = run.graph(which)
    text = to_graphml(g) if fmt == "graphml" else json.dumps(g, ensure_ascii=False, indent=1)
    out = out or Path(run_dir) / f"graph-{which}.{ 'graphml' if fmt == 'graphml' else 'json'}"
    out.write_text(text, encoding="utf-8")
    console.print(f"{len(g['nodes'])} nodes, {len(g['edges'])} edges → {out}")
    if compare:
        for k, c in g["summary"]["nodes"].items():
            console.print(f"  {k}: kept {c['kept']}, changed {c['changed']}, only source {c['source_only']}, "
                          f"only synthetic {c['synthetic_only']} (recall {c['recall']})")


@app.command("list")
def list_runs(runs_dir: Path = typer.Option(Path("runs"), "--runs-dir")):
    """List runs."""
    t = Table("id", "preset", "mode", "lang", "status", "$")
    for m in Saga.list_runs(runs_dir):
        t.add_row(m["id"], str(m["preset"]), str(m["mode"]), str(m["language"]), str(m["status"]), f"{m['cost_usd']:.3f}")
    console.print(t)


@app.command()
def presets():
    """List built-in presets."""
    t = Table("preset", "description")
    for name in preset_names():
        t.add_row(name, " ".join(load_config(name).description.split()))
    console.print(t)


@app.command()
def stages():
    """List registered stage implementations."""
    from psalm_saga.stages import available

    for name, impls in sorted(available().items()):
        console.print(f"[bold]{name}[/]: {', '.join(sorted(impls))}")


@app.command()
def config(preset: str = typer.Argument("full"), set_: list[str] = typer.Option([], "--set", "-s")):
    """Print the fully resolved configuration (after inheritance and overrides) as YAML."""
    console.print(yaml.safe_dump(load_config(preset, set_).model_dump(mode="json"), sort_keys=False, allow_unicode=True))


@app.command("eval")
def eval_(run_dir: Path):
    """Recompute the automatic evaluation of a run."""
    r = Saga.open(run_dir)
    r.run(only=["evaluate"])
    _summary(r)


@app.command()
def experiment(
    plan: Path,
    dry_run: bool = typer.Option(False, "--dry-run", help="List the jobs without running them."),
    set_: list[str] = typer.Option([], "--set", "-s", help="Overrides applied to every condition."),
    judge: bool = typer.Option(True, "--judge/--no-judge", help="Run model-judge instruments after generation."),
):
    """Run an experiment grid (inputs x conditions x models x repeats); resumable."""
    from psalm_saga.experiments.runner import run_experiment

    asyncio.run(run_experiment(plan, dry_run=dry_run, extra_overrides=set_, judge=judge, console=console))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8765, runs_dir: Path = typer.Option(Path("runs"), "--runs-dir")):
    """Start the web app."""
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter("Install the web extra: pip install 'psalm-saga[web]'") from exc
    from psalm_saga.web.app import create_app

    console.print(f"PSALM-SAGA web app on http://{host}:{port}  (runs: {runs_dir.resolve()})")
    uvicorn.run(create_app(runs_dir), host=host, port=port, log_level="warning")


@app.command()
def chat(
    run_dir: Path = typer.Argument(None, help="Open an existing run; omit to start a new one."),
    preset: str = typer.Option("full", "--preset", "-p"),
    set_: list[str] = typer.Option([], "--set", "-s"),
    model: str = typer.Option(None, "--model", "-m"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
):
    """Interactive session: build a run step by step, inspect and edit artifacts in plain language."""
    from psalm_saga.cli.repl import Repl

    Repl(console, preset=preset, overrides=_overrides(set_, model, None, None, None), runs_dir=runs_dir,
         run_dir=run_dir, progress=Progress()).loop()


if __name__ == "__main__":
    app()


__all__ = ["EDITABLE", "app"]
