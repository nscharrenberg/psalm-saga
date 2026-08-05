import csv
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal, Callable, Sequence

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from psalm_saga import StoryBible, Settings
from psalm_saga.agents import build_orchestrator
from psalm_saga.dataset_utils import decide_dataset_item_action
from psalm_saga.dimensions import PSALM_DIMENSIONS, DivergenceIntensity, DivergencePlan, evaluate_fidelity, \
    GenerationMode, IsolationStrategy, LengthTier, build_isolation_matrix
from psalm_saga.session import session_dir_for, init_session, checkpoint_db_path

ProgressCallback = Callable[[str, str, int, int], None]
"""Called as (source_file_name, variant_name, items_done, items_total) after each item."""


@dataclass(frozen=True, slots=True)
class DatasetItem:
    session_id: str
    source_file: str
    variant_name: str
    intended: dict[str, str]
    achieved: dict[str, str]
    mismatches: list[dict[str, str]]
    source_path: str
    final_story_path: str | None
    status: Literal["ok", "skipped_existing", "failed"]
    error: str = ""


def _drive_noninteractive(orchestrator, thread_config: dict,
                          initial_input: object) -> dict:  # type: ignore[type-arg,no-untyped-def]
    """
    Handles non-interactive orchestration by executing commands without human intervention.

    This function utilizes an `orchestrator` to invoke operations determined by the
    `initial_input` and `thread_config`. If an interruption occurs during the process,
    it retries with a default command. If a second interruption still occurs, it raises
    a `RuntimeError` to prevent the operation from stalling indefinitely. The return
    value typically contains the results of the orchestrator's processing.

    :param orchestrator: The orchestrator responsible for invoking commands to drive
        non-interactive workflow processes.
    :param thread_config: Configuration parameters as a dictionary to customize the behavior
        of the orchestrator during workflow execution.
    :type thread_config: dict
    :param initial_input: Initial input object that specifies the operation to be invoked
        by the orchestrator.
    :return: A dictionary containing the results of the orchestrator's execution. If
        exceptions occur during execution, they will either be retried or an error will
        be raised.
    :rtype: dict
    """
    result = orchestrator.invoke(initial_input, config=thread_config)

    if result.get("__interrupt__"):
        result = orchestrator.invoke(
            Command(resume="No human is available. Make your own reasonable decision and continue."),
            config=thread_config,
        )
    if result.get("__interrupt__"):
        raise RuntimeError(
            "Session paused on a second interrupt with no human available to answer it; "
            "aborting this dataset item rather than hanging."
        )

    return result  # type: ignore[no-any-return]


def _dataset_item_from_session_dir(
        session_dir: Path,
        *,
        source_path: Path,
        variant_name: str,
        plan: DivergencePlan,
        status: Literal["ok", "skipped_existing"],
) -> DatasetItem:
    """
    Creates a DatasetItem instance based on the provided session directory and associated information.

    This function constructs a DatasetItem by analyzing the contents of a session
    directory, including divergence data from a story bible and any mismatches
    between the intended and achieved divergence plans. If a final story file
    exists within the session directory, its path is included in the DatasetItem.

    :param session_dir: The directory containing session-related data used
        for constructing the DatasetItem.
    :type session_dir: Path
    :param source_path: The path to the source file relevant to the session.
    :type source_path: Path
    :param variant_name: The name of the variant associated with the session.
    :type variant_name: str
    :param plan: The intended divergence plan for the session.
    :type plan: DivergencePlan
    :param status: The processing status for this session. Can be either "ok"
        or "skipped_existing".
    :type status: Literal["ok", "skipped_existing"]
    :return: A DatasetItem instance containing information derived from
        the provided session directory, including achievement data, mismatches,
        paths, and metadata.
    :rtype: DatasetItem
    """
    bible_path = session_dir / "story_bible.json"
    achieved: dict[str, DivergenceIntensity] = {}
    mismatches: list[dict[str, str]] = []

    if bible_path.exists():
        bible = StoryBible.model_validate_json(bible_path.read_text(encoding="utf-8"))
        achieved = bible.achieved_divergence

        if bible.divergence_plan is not None:
            mismatches = [m.model_dump(mode="json") for m in evaluate_fidelity(bible.divergence_plan, achieved)]

    final_story = session_dir / "final_story.md"

    return DatasetItem(
        session_id=session_dir.name,
        source_file=source_path.name,
        variant_name=variant_name,
        intended={dim: level.value for dim, level in plan.per_dimension.items()},
        achieved={dim: level.value for dim, level in achieved.items()},
        mismatches=mismatches,
        source_path=str(source_path),
        final_story_path=str(final_story) if final_story.exists() else None,
        status=status,
    )


def run_dataset_item(
        settings: Settings,
        source_path: Path,
        variant_name: str,
        plan: DivergencePlan,
        *,
        context: str = "",
        overwrite: bool = False,
        length_tier: LengthTier = LengthTier.SHORT,
) -> DatasetItem:
    """
    Executes a dataset item creation process, managing sessions and handling divergence plans. This
    function drives the generation process from the source data, producing a dataset item based on
    the given parameters and settings. It supports both overwriting existing sessions and
    skipping execution for existing sessions when overwrite is disabled.

    :param settings: The configuration settings for dataset item creation.
    :type settings: Settings
    :param source_path: The file path to the source data used for generating the dataset item.
    :type source_path: Path
    :param variant_name: The name of the variant for the dataset item being created.
    :type variant_name: str
    :param plan: The divergence plan that outlines the intended properties for the dataset item.
    :type plan: DivergencePlan
    :param context: Additional context or information to include during the process. Defaults to an
        empty string.
    :type context: str, optional
    :param overwrite: Specifies whether to overwrite the existing session directory if it exists.
        Defaults to False.
    :type overwrite: bool, optional
    :return: A dataset item object representing the outcome of the process. Its status indicates
        success, failure, or whether an existing session was skipped.
    :rtype: DatasetItem
    """
    session_id = f"{source_path.stem}__{variant_name}"
    session_dir = session_dir_for(settings, session_id)

    decision = decide_dataset_item_action(session_dir, overwrite=overwrite)
    if decision == "reuse_finished":
        return _dataset_item_from_session_dir(
            session_dir,
            source_path=source_path,
            variant_name=variant_name,
            plan=plan,
            status="skipped_existing"
        )

    if session_dir.exists():
        shutil.rmtree(session_dir) # either overwrite=True, or a failed/partial leftover -- retry

    try:
        session_dir = init_session(
            settings,
            GenerationMode.FROM_SOURCE,
            source_path=source_path,
            initial_context=context,
            session_id=session_id,
            divergence_plan=plan,
            non_interactive=True,
            length_tier=length_tier,
        )

        with SqliteSaver.from_conn_string(str(checkpoint_db_path(session_dir))) as checkpointer:
            orchestrator = build_orchestrator(settings, session_dir, checkpointer, non_interactive=True)
            thread_config = {"configurable": {"thread_id": session_id}}
            kickoff = (
                "Begin a from_source session. The source text is at source.txt in the working "
                "directory. A divergence_plan has already been set on story_bible.json -- it is "
                "final; do not renegotiate it, proceed directly through extraction and writing. "
                f"Additional context: {context or '(none)'}"
            )
            _drive_noninteractive(
                orchestrator,
                thread_config,
                {
                    "messages": [HumanMessage(kickoff)],
                    "mode": GenerationMode.FROM_SOURCE.value,
                    "session_id": session_id,
                },
            )
    except Exception as exc:  # noqa: BLE001 - one failed item must not abort the whole batch
        return DatasetItem(
            session_id=session_id,
            source_file=source_path.name,
            variant_name=variant_name,
            intended={dim: level.value for dim, level in plan.per_dimension.items()},
            achieved={},
            mismatches=[],
            source_path=str(source_path),
            final_story_path=None,
            status="failed",
            error=str(exc),
        )

    return _dataset_item_from_session_dir(
        session_dir,
        source_path=source_path,
        variant_name=variant_name,
        plan=plan,
        status="ok"
    )


def run_batch(
        settings: Settings,
        sources_dir: Path,
        *,
        dimensions: Sequence[str] = PSALM_DIMENSIONS,
        strategy: IsolationStrategy = "isolate_preserve",
        include_baselines: bool = True,
        near: DivergenceIntensity = DivergenceIntensity.CLOSE,
        far: DivergenceIntensity = DivergenceIntensity.DIVERGENT,
        context: str = "",
        overwrite: bool = False,
        length_tier: LengthTier = LengthTier.SHORT,
        progress_callback: ProgressCallback | None = None,
) -> list[DatasetItem]:
    """
    Executes a batch operation over source files to generate dataset items based on the provided settings
    and isolation strategy. The function processes files in the specified source directory and creates
    dataset variants defined by the isolation matrix.

    :param settings: An instance of the `Settings` object that holds configuration details for the
        batch operation.
    :param sources_dir: The directory where source files to be processed are located.
    :param dimensions: A sequence of dimension names to be used for constructing the isolation matrix.
        Default value uses PSALM_DIMENSIONS.
    :param strategy: The strategy specifying how the isolation matrix should be built. By default,
        it is "isolate_preserve".
    :param include_baselines: A boolean indicating whether baseline variants should be included in
        the isolation matrix. Defaults to True.
    :param near: A `DivergenceIntensity` enumeration indicating the "near" divergence intensity level.
        Defaults to `DivergenceIntensity.CLOSE`.
    :param far: A `DivergenceIntensity` enumeration indicating the "far" divergence intensity level.
        Defaults to `DivergenceIntensity.DIVERGENT`.
    :param context: An optional string to be associated with the processing context. Defaults to an
        empty string.
    :param overwrite: A boolean indicating whether existing dataset items should be overwritten. Defaults
        to False.
    :param progress_callback: An optional callable used to report progress. The callback takes four
        arguments: the name of the current source file, the name of the current variant, the count of
        items processed so far, and the total number of items to process. If not provided, no progress
        will be reported.
    :return: A list of `DatasetItem` objects representing the processed datasets generated for each
        source file and variant.
    """
    source_files = sorted(p for p in sources_dir.iterdir() if p.is_file())

    if not source_files:
        raise ValueError(f"No source files found in \"{sources_dir}\"")

    variants = build_isolation_matrix(
        dimensions=dimensions,
        strategy=strategy,
        near=near,
        far=far,
        include_baselines=include_baselines,
    )

    total = len(source_files) * len(variants)
    done = 0
    items: list[DatasetItem] = []
    for source_path in source_files:
        for variant_name, plan in variants.items():
            item = run_dataset_item(
                settings,
                source_path,
                variant_name,
                plan,
                context=context,
                overwrite=overwrite,
                length_tier=length_tier,
            )

            items.append(item)
            done += 1

            if progress_callback is not None:
                progress_callback(source_path.name, variant_name, done, total)

    return items

def write_manifest(items: Sequence[DatasetItem], output_path: Path) -> None:
    """
    Writes a manifest file in JSON and CSV formats based on a sequence of DatasetItem
    objects and saves it to the specified output path.

    The function generates the JSON manifest by serializing the properties of the
    DatasetItem objects into a JSON structure. Additionally, it creates a CSV
    manifest containing detailed information including calculated fields for
    intended and achieved dimensions.

    :param items: A sequence of DatasetItem objects that contain the data to be
        included in the manifest.
    :type items: Sequence[DatasetItem]
    :param output_path: The file path where the JSON and corresponding CSV
        manifests will be saved. The parent directories will be created if they do
        not exist.
    :type output_path: Path
    :return: None
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([asdict(item) for item in items], indent=2), encoding="utf-8")

    csv_path = output_path.with_suffix(".csv")
    field_names = [
        "session_id",
        "source_file",
        "variant_name",
        "status",
        "error",
        "n_mismatches",
        "final_story_path",
        "source_path",
        *(f"intended_{dim}" for dim in PSALM_DIMENSIONS),
        *(f"achieved_{dim}" for dim in PSALM_DIMENSIONS),
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_names)
        writer.writeheader()

        for item in items:
            row = {
                "session_id": item.session_id,
                "source_file": item.source_file,
                "variant_name": item.variant_name,
                "status": item.status,
                "error": item.error,
                "n_mismatches": len(item.mismatches),
                "final_story_path": item.final_story_path or "",
                "source_path": item.source_path,
            }

            for dim in PSALM_DIMENSIONS:
                row[f"intended_{dim}"] = item.intended.get(dim, "")
                row[f"achieved_{dim}"] = item.achieved.get(dim, "")

            writer.writerow(row)
