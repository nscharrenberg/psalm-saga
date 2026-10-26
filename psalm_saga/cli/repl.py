"""Interactive session, in the spirit of Claude Code: slash commands for control, and
free text as an instruction applied to the artifact currently in focus.

The default flow pauses after the spec and after the plan, so a person can steer the
story before any prose is written:  /new -> spec (review, edit) -> plan (review, edit) -> write.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from psalm_saga.sdk import EDITABLE, Run, Saga

HELP = """
**Start**  `/new <file|text>` (source text, premise, or spec .json) · `/open <run_dir>`
**Run**    `/next` run up to the next checkpoint (spec → plan → story) · `/run` run to the end · `/rerun <stage>`
**Look**   `/show [story|spec|spec_source|bible|plan|transform|evaluation|chapter:N]` · `/status` · `/eval`
**Change** `/focus <artifact>` then type an instruction in plain language, or `/edit <artifact> <instruction>`
           `/set key=value` (config override, e.g. `/set stages.review.enabled=false`)
**Other**  `/help` · `/quit`

Free text with no run open starts a new run with that text as the premise.
"""

CHECKPOINTS = ["spec", "plan", None]


class Repl:
    def __init__(self, console: Console, *, preset: str, overrides: list[str], runs_dir: Path, run_dir: Path | None,
                 progress):
        self.c = console
        self.preset = preset
        self.overrides = list(overrides)
        self.runs_dir = runs_dir
        self.progress = progress
        self.run: Run | None = Saga.open(run_dir, on_event=progress) if run_dir else None
        self.focus = self._default_focus()

    def _default_focus(self) -> str:
        if not self.run:
            return "spec"
        if self.run.store.exists("chapters"):
            return "chapter:1"
        if self.run.store.exists("plan.json"):
            return "plan"
        return "spec"

    def loop(self) -> None:
        self.c.print(Markdown("# PSALM-SAGA\nType `/help` for commands."))
        if self.run:
            self.c.print(f"opened {self.run.path}")
        while True:
            try:
                line = self.c.input(f"[bold magenta]saga[/][dim]({self.focus})[/]> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.c.print()
                return
            if not line:
                continue
            try:
                if line.startswith("/"):
                    if self.command(line) is False:
                        return
                elif self.run is None:
                    self.new(line)
                else:
                    self.c.print(f"[dim]editing {self.focus}…[/]")
                    self.run.edit(self.focus, line)
                    self.show(self.focus)
            except Exception as exc:  # keep the session alive
                self.c.print(f"[red]{type(exc).__name__}: {exc}[/]")

    def new(self, arg: str) -> None:
        from psalm_saga.cli.main import _read_input

        saga = Saga(self.preset, overrides=self.overrides, runs_dir=self.runs_dir, on_event=self.progress)
        self.run = saga.create(**_read_input(arg, "auto"))
        self.c.print(f"new run {self.run.path} (mode {self.run.pipeline.mode}, language {self.run.pipeline.language()}). "
                     "`/next` builds the spec.")
        self.focus = "spec"

    def next(self) -> None:
        assert self.run
        for stop in CHECKPOINTS:
            names = [s.name for s in self.run.pipeline.stages()]
            target = stop if stop in names else None
            done_target = target and self.run.store.exists("spec.json" if target == "spec" and self.run.pipeline.mode != "source" else
                                                           ("spec.json" if target == "spec" else "plan.json"))
            if stop is not None and done_target:
                continue
            self.run.run(until=target)
            if target:
                self.focus = target
                self.show(target)
                self.c.print(f"[dim]Checkpoint: {target}. Edit it in plain language, or `/next` to continue.[/]")
            else:
                self.focus = "chapter:1"
                self.c.print(f"[green]Story written:[/] {self.run.path / 'story.md'}")
            return

    def show(self, what: str = "story") -> None:
        assert self.run
        if what == "story":
            self.c.print(Markdown(self.run.story or "(no story yet)"))
            return
        a = self.run.artifact(what)
        if a is None:
            self.c.print(f"(no {what} yet)")
        elif hasattr(a, "render"):
            self.c.print(Markdown(a.render()))
        elif what == "plan":
            for ch in a.chapters:
                self.c.print(f"[bold]{ch.index}. {ch.title}[/] ({ch.target_words} w, {len(ch.scenes)} scenes) — {ch.summary}")
        elif what.startswith("chapter:"):
            self.c.print(Markdown(f"## {a.title}\n\n{a.text}"))
        else:
            self.c.print_json(a.model_dump_json() if hasattr(a, "model_dump_json") else __import__("json").dumps(a, ensure_ascii=False))

    def command(self, line: str):
        parts = shlex.split(line)
        cmd, args = parts[0][1:], parts[1:]
        if cmd in ("quit", "exit", "q"):
            return False
        if cmd == "help":
            self.c.print(Markdown(HELP))
        elif cmd == "new":
            self.new(" ".join(args))
        elif cmd == "open":
            self.run = Saga.open(args[0], on_event=self.progress)
            self.focus = self._default_focus()
        elif self.run is None:
            self.c.print("No run open: `/new <file|text>` or `/open <run_dir>`.")
        elif cmd == "next":
            self.next()
        elif cmd == "run":
            self.run.run()
            self.c.print(f"[green]done[/] → {self.run.path / 'story.md'}")
        elif cmd == "rerun":
            self.run.run(rerun_from=args[0])
        elif cmd == "show":
            self.show(args[0] if args else "story")
        elif cmd == "status":
            for s in self.run.status()["stages"]:
                self.c.print(f"{'✓' if s['done'] else '·'} {s['name']} [dim]{s['impl']}{'' if s['applies'] else ' (n/a)'}[/]")
        elif cmd == "eval":
            self.run.run(only=["evaluate"])
            self.show("evaluation")
        elif cmd == "focus":
            if not args or not (args[0] in EDITABLE or args[0].startswith(("chapter:", "chapter_plan:"))):
                self.c.print(f"focus on one of: {', '.join(EDITABLE)}, chapter:N, chapter_plan:N")
            else:
                self.focus = args[0]
        elif cmd == "edit":
            self.run.edit(args[0], " ".join(args[1:]))
            self.show(args[0])
        elif cmd == "set":
            self.overrides += args
            self.run = Saga.open(self.run.path, overrides=args, on_event=self.progress)
            self.c.print(f"set {' '.join(args)}")
        else:
            self.c.print(f"unknown command /{cmd} — /help")
        return None
