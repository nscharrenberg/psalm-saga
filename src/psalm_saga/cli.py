import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Annotated

import typer
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from psalm_saga.agents import build_orchestrator
from psalm_saga.batch import run_batch, write_manifest, build_isolation_matrix
from psalm_saga.config import Settings
from psalm_saga.dimensions import GenerationMode, DivergencePlan, DivergenceIntensity, PSALM_DIMENSIONS
from psalm_saga.session import init_session, checkpoint_db_path, SessionConfig, load_session_config

app = typer.Typer(
    name="psalm-saga",
    help="PSALM-SAGA: generate synthetic stories from scratch or from a source text.",
    no_args_is_help=True,
)
console = Console()


def _build_settings(
        model: str | None,
        subagent_model: str | None,
        sessions_root: Path | None,
        guard_strictness: str | None,
) -> Settings:
    """
    Builds a `Settings` object using the provided parameters as overrides.

    This function allows customization of the `Settings` object by conditionally
    adding override values for specific configuration parameters if they are
    provided. Each parameter, when not `None`, is added to an internal dictionary
    of overrides which is then used to construct the `Settings` instance.

    :param model: Optional model identifier to be used as an override.
    :param subagent_model: Optional subagent model identifier for customization.
    :param sessions_root: Optional path to the root directory for sessions.
    :param guard_strictness: Optional string for specifying originality guard
        strictness level.
    :return: A `Settings` instance configured using the provided overrides.
    :rtype: Settings
    """
    overrides: dict[str, object] = {}

    if model is not None:
        overrides["model"] = model

    if subagent_model is not None:
        overrides["subagent_model"] = subagent_model

    if sessions_root is not None:
        overrides["sessions_root"] = sessions_root

    if guard_strictness is not None:
        overrides["originality_guard_strictness"] = guard_strictness

    return Settings(**overrides)  # type: ignore[arg-type]


def _print_final(result: dict) -> None:  # type: ignore[type-arg]
    """
    Processes and displays the final content from the provided result dictionary. The method extracts
    the last message from the "messages" list within the result, formats its content, and
    prints it using a styled panel using the `rich` library.

    :param result: Dictionary containing a "messages" key with a list of message objects or strings.
    :type result: dict
    :return: None
    """
    messages = result.get("messages", [])

    if not messages:
        return

    last = messages[-1]
    content = getattr(last, "content", str(last))

    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )

    console.print(Panel(Markdown(content), title="PSALM-SAGA", border_style="green"))


def _run_until_done(orchestrator, config: dict, initial_input: object) -> None:  # type: ignore[type-arg,no-untyped-def]
    """
    Executes a loop that processes the orchestrator's tasks until there are no more
    interrupts. Handles manual user input when interruptions occur and resumes
    execution based on the provided input.

    :param orchestrator: The object responsible for coordinating task invocation and
        handling the processing logic. Must implement the `invoke` method for
        executing tasks.
    :param config: Dictionary containing configuration parameters required by the
        orchestrator. Used to provide context for task invocation and execution.
    :param initial_input: The initial object or command passed to the orchestrator to
        begin the loop. Subsequent inputs are derived from user responses.
    :return: None
    """
    result = orchestrator.invoke(initial_input, config=config)

    while interrupts := result.get("__interrupt__"):
        # deepagents' ask_human raises a single interrupt per pause; handle each in order in the
        # (rare) case multiple are batched by the underlying runtime.

        for pending in interrupts:
            payload = pending.value if hasattr(pending, "value") else pending
            question = payload.get("question", str(payload))
            why = payload.get("why")
            body = question if not why else f"{question}\n\n[dim]{why}[/dim]"
            console.print(Panel(body, title="PSALM-SAGA asks", border_style="cyan"))
            answer = Prompt.ask("[bold cyan]Your answer[/bold cyan]")
            result = orchestrator.invoke(Command(resume=answer), config=config)

    _print_final(result)


@app.command()
def new(
        context: Annotated[
            str, typer.Option("--context", "-c", help="Optional seed context/idea, free text.")
        ] = "",
        source: Annotated[
            Path | None,
            typer.Option("--source", "-s", help="Path to a source text to generate from."),
        ] = None,
        model: Annotated[
            str | None,
            typer.Option(
                "--model",
                "-m",
                help="provider:model string, e.g. anthropic:claude-opus-4-8. "
                     "Falls back to PSALM_SAGA_MODEL env var.",
            ),
        ] = None,
        subagent_model: Annotated[
            str | None, typer.Option("--subagent-model", help="Override model for subagents.")
        ] = None,
        sessions_root: Annotated[
            Path | None, typer.Option("--sessions-root", help="Where session directories live.")
        ] = None,
        guard_strictness: Annotated[
            str | None,
            typer.Option(
                "--guard-strictness", help="'warn' or 'block' (from_scratch mode only).", show_default=False
            ),
        ] = None,
        session_name: Annotated[
            str | None, typer.Option("--session-name", help="Custom session id instead of a generated one.")
        ] = None,
        divergence_plan_file: Annotated[
            Path | None,
            typer.Option(
                "--divergence-plan",
                help=(
                        "JSON file with a per-dimension divergence plan, e.g. "
                        '{"characters": "close", "plot": "divergent", ...} (from_source mode only). '
                        "Must cover all six PSALM dimensions. Skips the brainstorm negotiation step."
                ),
            ),
        ] = None,
        non_interactive: Annotated[
            bool,
            typer.Option(
                "--non-interactive",
                help="Never pause for questions -- the agent makes its own decisions instead. "
                     "Implied by --divergence-plan. For batch/scripted use, see `saga batch`.",
            ),
        ] = False,
) -> None:
    """
    Start a new story-generation session. The session can be
    initialized from scratch with an optional context or from a source text file. Relevant settings
    are configured before session initialization, and the session is actively managed through an
    orchestrator.

    :param context: Optional seed context or idea in free text. If not provided, an empty context is used.
    :type context: str
    :param source: Path to a source text file for generation. Can be None if generating from scratch.
    :type source: Path | None
    :param model: The provider:model string (e.g., 'anthropic:claude-opus-4-8') for the main generative
        model. Falls back to the `PSALM_SAGA_MODEL` environment variable if not provided.
    :type model: str | None
    :param subagent_model: Optional override for the model used by subagents.
    :type subagent_model: str | None
    :param sessions_root: Optional base directory where session directories are stored.
    :type sessions_root: Path | None
    :param guard_strictness: Guard behavior when generating from scratch. Possible values are 'warn' or
        'block'. This option has no default value.
    :type guard_strictness: str | None
    :param session_name: A custom session identifier. If not provided, a default ID will be generated.
    :type session_name: str | None
    :return: None
    """
    settings = _build_settings(model, subagent_model, sessions_root, guard_strictness)
    mode = GenerationMode.FROM_SOURCE if source is not None else GenerationMode.FROM_SCRATCH

    divergence_plan: DivergencePlan | None = None
    if divergence_plan_file is not None:
        if mode is not GenerationMode.FROM_SOURCE:
            console.print("[red]--divergence-plan only applies to from_source mode (pass --source).[/red]")
            raise typer.Exit(code=1)
        raw = json.loads(divergence_plan_file.read_text(encoding="utf-8"))
        divergence_plan = DivergencePlan(
            per_dimension={dim: DivergenceIntensity(level) for dim, level in raw.items()}
        )
        non_interactive = True

    session_dir = init_session(
        settings,
        mode,
        source_path=source,
        initial_context=context,
        session_id=session_name,
        divergence_plan=divergence_plan,
        non_interactive=non_interactive,
    )
    console.print(f"[green]Session created:[/green] \"{session_dir}\"")

    with SqliteSaver.from_conn_string(str(checkpoint_db_path(session_dir))) as checkpointer:
        orchestrator = build_orchestrator(settings, session_dir, checkpointer, non_interactive=non_interactive)
        thread_config = {
            "configurable": {
                "thread_id": session_dir.name
            }
        }

        if mode is GenerationMode.FROM_SCRATCH:
            kickoff = (
                "Begin a from_scratch session. "
                f"Initial context from the user: \"{context or '(none provided)'}\""
            )
        else:
            plan_note = (
                " A divergence_plan has already been set on story_bible.json -- it is final; do "
                "not renegotiate it."
                if divergence_plan is not None
                else ""
            )
            kickoff = (
                "Begin a from_source session. The source text is at source.txt in the working "
                f"directory.{plan_note} Initial context/instructions from the user: "
                f"{context or '(none provided)'}"
            )

        _run_until_done(
            orchestrator,
            thread_config,
            {
                "messages": [HumanMessage(kickoff)],
                "mode": mode.value,
                "session_id": session_dir.name
            }
        )


@app.command()
def resume(
        session_id: Annotated[str, typer.Argument(help="Session id (the directory name).")],
        sessions_root: Annotated[
            Path | None, typer.Option("--sessions-root", help="Where session directories live.")
        ] = None,
        model: Annotated[str | None, typer.Option("--model", "-m", help="Override the session's model.")] = None,
) -> None:
    root = sessions_root or Settings.model_fields["sessions_root"].get_default()
    session_dir = Path(root) / session_id

    if not session_dir.exists():
        console.print(f"[red]No such session:[/red] \"{session_dir}\"")
        raise typer.Exit(code=1)

    saved: SessionConfig = load_session_config(session_dir)
    settings = _build_settings(
        model or saved.model,
        saved.subagent_model,
        sessions_root,
        saved.originality_guard_strictness,
    )

    with SqliteSaver.from_conn_string(str(checkpoint_db_path(session_dir))) as checkpointer:
        orchestrator = build_orchestrator(
            settings, session_dir, checkpointer, non_interactive=saved.non_interactive
        )
        thread_config = {
            "configurable": {
                "thread_id": session_id
            }
        }

        state = orchestrator.get_state(thread_config)
        has_pending_interrupt = bool(state.tasks and any(t.interrupts for t in state.tasks))

        if has_pending_interrupt:
            console.print("[yellow]Resuming a pending question...[/yellow]")
            _run_until_done(orchestrator, thread_config, None)
        else:
            follow_up = Prompt.ask(
                "[bold cyan]No pending question. What would you like to tell the agent?[/bold cyan]"
            )
            _run_until_done(orchestrator, thread_config, {"messages": [HumanMessage(follow_up)]})


@app.command()
def batch(
        sources_dir: Annotated[Path, typer.Argument(help="Directory of source text files.")],
        model: Annotated[
            str | None, typer.Option("--model", "-m", help="provider:model string.")
        ] = None,
        subagent_model: Annotated[
            str | None, typer.Option("--subagent-model", help="Override model for subagents.")
        ] = None,
        sessions_root: Annotated[
            Path | None, typer.Option("--sessions-root", help="Where session directories live.")
        ] = None,
        dimensions: Annotated[
            str,
            typer.Option(
                "--dimensions",
                help="Comma-separated PSALM dimensions to generate isolation variants for.",
            ),
        ] = ",".join(PSALM_DIMENSIONS),
        strategy: Annotated[
            str,
            typer.Option(
                "--strategy",
                help="'isolate_preserve' (hold one dimension close, vary the rest -- default) or "
                     "'isolate_vary' (vary one dimension, hold the rest close).",
            ),
        ] = "isolate_preserve",
        include_baselines: Annotated[
            bool,
            typer.Option(
                "--include-baselines/--no-include-baselines",
                help="Also generate an all-close and an all-divergent baseline per source.",
            ),
        ] = True,
        near: Annotated[
            str, typer.Option("--near", help="Intensity level used for the 'similar' side.")
        ] = "close",
        far: Annotated[
            str, typer.Option("--far", help="Intensity level used for the 'different' side.")
        ] = "divergent",
        context: Annotated[
            str, typer.Option("--context", "-c", help="Extra context/instructions applied to every item.")
        ] = "",
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite", help="Regenerate items whose session directory already exists."),
        ] = False,
        output: Annotated[
            Path | None,
            typer.Option("--output", "-o", help="Manifest path (.json; a sibling .csv is also written)."),
        ] = None,
) -> None:
    """
    Batch processes a directory of source text files to generate isolation variants and save the results.

    This command takes a directory of source text files and applies the specified processing strategy
    to generate varying isolation variants of the source data. Additional context and specific
    parameters can be included to modify the output behavior. A manifest file summarizing the batch
    operation is created upon completion.

    :param sources_dir: Directory of source text files.
    :param model: Provider:model string (optional). Overrides the default model setting.
    :param subagent_model: Model string for subagents (optional). Overrides model for subagents.
    :param sessions_root: Path to the sessions root directory (optional). Determines where session
        directories are stored.
    :param dimensions: Comma-separated PSALM dimensions for generating isolation variants.
    :param strategy: Processing strategy to use. 'isolate_preserve' (default) holds one dimension
        close and varies the rest, while 'isolate_vary' varies one dimension and holds the rest close.
    :param include_baselines: Whether to include an all-close and all-divergent baseline per source.
    :param near: Intensity level used for the 'similar' side.
    :param far: Intensity level used for the 'different' side.
    :param context: Additional context or instructions applied to each item.
    :param overwrite: Whether to regenerate items whose session directory already exists.
    :param output: Path to save the manifest (.json file along with a sibling .csv file). If not
        provided, a default path based on timestamp is used.

    :return: None
    """
    settings = _build_settings(model, subagent_model, sessions_root, None)
    dim_list = [d.strip() for d in dimensions.split(",") if d.strip()]

    def _on_progress(source_name: str, variant_name: str, done: int, total: int) -> None:
        console.print(f"[cyan]({done}/{total})[/cyan] {source_name} :: {variant_name}")

    items = run_batch(
        settings,
        sources_dir,
        dimensions=dim_list,
        strategy=strategy,  # type: ignore[arg-type]
        include_baselines=include_baselines,
        near=DivergenceIntensity(near),
        far=DivergenceIntensity(far),
        context=context,
        overwrite=overwrite,
        progress_callback=_on_progress,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    manifest_path = output or (settings.sessions_root / f"batch-manifest-{stamp}.json")
    write_manifest(items, manifest_path)

    ok = sum(1 for i in items if i.status == "ok")
    skipped = sum(1 for i in items if i.status == "skipped_existing")
    failed = sum(1 for i in items if i.status == "failed")
    total_mismatches = sum(len(i.mismatches) for i in items)

    console.print(
        f"[green]Done:[/green] {ok} generated, {skipped} skipped (already existed), "
        f"{failed} failed. {total_mismatches} fidelity mismatch(es) across all items."
    )
    console.print(f"Manifest: {manifest_path} (and {manifest_path.with_suffix('.csv')})")
    if failed:
        console.print("[yellow]Failed items (see manifest for details):[/yellow]")
        for item in items:
            if item.status == "failed":
                console.print(f"  - {item.session_id}: {item.error}")


@app.command()
def isolation_matrix(
        dimensions: Annotated[
            str,
            typer.Option("--dimensions", help="Comma-separated PSALM dimensions."),
        ] = ",".join(PSALM_DIMENSIONS),
        strategy: Annotated[str, typer.Option("--strategy")] = "isolate_preserve",
        include_baselines: Annotated[bool, typer.Option("--include-baselines/--no-include-baselines")] = True,
        near: Annotated[str, typer.Option("--near")] = "close",
        far: Annotated[str, typer.Option("--far")] = "divergent",
) -> None:
    dim_list = [d.strip() for d in dimensions.split(",") if d.strip()]

    variants = build_isolation_matrix(
        dimensions=dim_list,
        strategy=strategy,  # type: ignore[arg-type]
        near=DivergenceIntensity(near),
        far=DivergenceIntensity(far),
        include_baselines=include_baselines,
    )

    payload = {name: {dim: level.value for dim, level in plan.per_dimension.items()} for name, plan in variants.items()}
    console.print(Panel(json.dumps(payload, indent=2), title="Isolation matrix", border_style="cyan"))


if __name__ == "__main__":
    app()
