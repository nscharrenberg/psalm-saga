"""Non-interactive batch entry point for psalm-saga.

Run `psalm-saga-batch` to generate many complete stories in one session
with no human interaction — see `docs/superpowers/specs/
2026-08-24-batch-story-generation-design.md` for the full design this
implements. Every story goes through the same spec -> plan -> draft ->
review pipeline an interactive session does; `batch-story-generation` (the
force-injected bootstrap for this session) and the "Autonomous Mode"
sections of `story-brainstorming`, `writing-story-plans`, and
`reviewing-story-dimensions` decide every dimension and sign-off a human
would normally handle.
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from psalm_saga.agent import build_agent, open_sqlite_checkpointer
from psalm_saga.batch_inputs import (
    BatchInputError,
    VariantSource,
    resolve_context_inputs,
    resolve_template_inputs,
    resolve_variant_sources,
)
from psalm_saga.batch_session import (
    drafts_dir,
    existing_story_names,
    promote_story,
    promoted_story_count,
    promoted_story_names,
)
from psalm_saga.bootstrap import BATCH_BOOTSTRAP_SKILL
from psalm_saga.session import generate_session_id, session_directory
from psalm_saga.settings import Settings
from psalm_saga.stream_renderer import StreamRenderer, extract_tool_call_lines

MAX_ATTEMPT_MULTIPLIER = 3


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="psalm-saga-batch",
        description="Generate many complete stories in one session, non-interactively.",
    )
    parser.add_argument(
        "--count", type=int, required=True, help="Target total finished stories in docs/stories/."
    )
    parser.add_argument(
        "--mode",
        choices=["scratch", "context", "template", "variant"],
        required=True,
        help="Where each story's premise/dimensions come from.",
    )
    parser.add_argument(
        "--context", action="append", default=[], dest="context_texts",
        help="Inline inspiration text (repeatable). --mode context.",
    )
    parser.add_argument(
        "--context-path", action="append", default=[], type=Path, dest="context_paths",
        help="Inspiration file or directory (repeatable). --mode context.",
    )
    parser.add_argument(
        "--template-path", action="append", default=[], type=Path, dest="template_paths",
        help="Template file or directory (repeatable). --mode template.",
    )
    parser.add_argument(
        "--source-path", action="append", default=[], type=Path, dest="source_paths",
        help="Source file or directory (repeatable). --mode variant.",
    )
    parser.add_argument(
        "--variant-manifest", type=Path, default=None, dest="variant_manifest",
        help="JSON manifest mapping source files to dimensions to vary. --mode variant.",
    )
    parser.add_argument(
        "--combine", choices=["mixed", "separate"], default=None,
        help="How multiple inputs map onto --count stories. Forced to 'separate' for --mode variant.",
    )
    parser.add_argument(
        "--session",
        dest="session_id",
        default=None,
        help="Resume/target a specific session id instead of starting a fresh one.",
    )
    parser.add_argument(
        "--model",
        dest="model",
        default=None,
        help="Override the main-loop model (e.g. anthropic:claude-sonnet-4-6).",
    )
    args = parser.parse_args(argv)

    if args.count < 1:
        parser.error("--count must be at least 1")

    if args.mode == "variant":
        if args.combine == "mixed":
            parser.error("--combine mixed is not valid with --mode variant")
        args.combine = "separate"
    elif args.combine is None:
        args.combine = "mixed"

    return args


def _resolve_inputs(args: argparse.Namespace) -> list[str] | list[VariantSource] | None:
    if args.mode == "scratch":
        return None
    if args.mode == "context":
        return resolve_context_inputs(args.context_texts, args.context_paths)
    if args.mode == "template":
        return resolve_template_inputs(args.template_paths)
    return resolve_variant_sources(args.source_paths, args.variant_manifest)


def _build_story_instruction(  # noqa: PLR0913, PLR0917
    story_index: int,
    count: int,
    mode: str,
    combine: str,
    inputs: list[str] | list[VariantSource] | None,
    existing_names: set[str],
) -> str:
    if mode == "variant":
        inputs_desc = json.dumps(
            [
                {
                    "source": str(source.source_path),
                    "dimensions": list(source.dimensions),
                    "content": source.content,
                }
                for source in inputs or []
            ]
        )
    elif mode == "scratch":
        inputs_desc = "(none — invent freely)"
    else:
        inputs_desc = json.dumps(inputs)

    return (
        f"Generate story {story_index} of {count}. Mode: {mode}. "
        f"Combine: {combine}. Inputs: {inputs_desc}. "
        f"Existing names in this session: {sorted(existing_names)}. "
        "Use the batch-story-generation skill."
    )


def _promote_finished_drafts(settings: Settings, session_id: str, console: Console) -> None:
    """Promote every draft directory carrying a `DONE.md` marker.

    `DONE.md`, not merely the absence of `ABANDONED.md`, is what marks a
    draft as promotable — a story whose turn ends abnormally (a caught
    exception mid-pipeline) leaves a draft with neither file, and that
    must never be mistaken for finished. Such a draft is simply skipped:
    not promoted, not abandoned, left as an inert partial on disk.
    """
    drafts = drafts_dir(settings, session_id)
    if not drafts.is_dir():
        return
    already_promoted = promoted_story_names(settings, session_id)
    for draft in sorted(p for p in drafts.iterdir() if p.is_dir()):
        if draft.name in already_promoted or not (draft / "DONE.md").is_file():
            continue
        promote_story(settings, session_id, draft.name)
        console.print(f"[dim]Promoted:[/dim] {draft.name}")


def run_batch(settings: Settings, args: argparse.Namespace, console: Console) -> None:
    """Generate stories until `docs/stories/` for this session holds
    `args.count` of them (or the overall attempt cap is hit).

    Never trusts the agent's own claim of success — after every per-story
    turn, `promoted_story_count` re-scans the filesystem, which is the only
    thing that decides whether the loop continues.
    """
    inputs = _resolve_inputs(args)

    session_id = args.session_id or generate_session_id()
    console.print(f"[dim]Session:[/dim] {session_id}")
    console.print(f"[dim]Session directory:[/dim] {session_directory(settings, session_id)}\n")

    with open_sqlite_checkpointer(settings, session_id) as checkpointer:
        agent = build_agent(
            settings,
            session_id=session_id,
            checkpointer=checkpointer,
            bootstrap_skill=BATCH_BOOTSTRAP_SKILL,
        )
        config = {"configurable": {"thread_id": session_id}}

        attempts = 0
        max_attempts = args.count * MAX_ATTEMPT_MULTIPLIER
        done = promoted_story_count(settings, session_id)

        while done < args.count and attempts < max_attempts:
            attempts += 1
            names = existing_story_names(settings, session_id)
            story_inputs = inputs
            if args.combine == "separate" and inputs:
                story_inputs = [inputs[done % len(inputs)]]
            message = _build_story_instruction(
                done + 1, args.count, args.mode, args.combine, story_inputs, names
            )
            console.print(f"[bold magenta]batch>[/bold magenta] attempt {attempts}: {message}\n")

            renderer = StreamRenderer(console)
            try:
                for stream_mode, payload in agent.stream(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                    stream_mode=["messages", "updates"],
                ):
                    if stream_mode == "messages":
                        chunk, metadata = payload
                        if metadata.get("langgraph_node") == "model":
                            renderer.add_token(getattr(chunk, "content", ""))
                    elif stream_mode == "updates":
                        for line in extract_tool_call_lines(payload):
                            renderer.announce_tool_call(line)
            except Exception as exc:  # noqa: BLE001 — a bad story shouldn't crash the whole batch
                renderer.finish()
                console.print(f"[red]Story attempt {attempts} failed: {exc}[/red]\n")
                continue
            renderer.finish()
            console.print()

            _promote_finished_drafts(settings, session_id, console)
            done = promoted_story_count(settings, session_id)
            console.print(f"[dim]Promoted so far:[/dim] {done}/{args.count}\n")

    if done < args.count:
        console.print(
            f"[yellow]Stopped after {attempts} attempts with {done}/{args.count} "
            "stories promoted.[/yellow]"
        )
    else:
        console.print(f"[bold green]Done.[/bold green] {done} stories in docs/stories/.")


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `psalm-saga-batch` console script."""
    load_dotenv()
    console = Console()

    args = _parse_args(argv)

    settings = Settings()
    if args.model:
        settings.agent.orchestration_model_name = args.model

    try:
        run_batch(settings, args, console)
    except BatchInputError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
