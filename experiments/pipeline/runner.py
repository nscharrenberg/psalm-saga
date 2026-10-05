"""Bounded worker pool: claims pending jobs, dispatches to backends, records results.

See spec §8.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from experiments.pipeline.backends import BACKEND_REGISTRY
from experiments.pipeline.models import GenerationJob, JobAbandoned, JobFailed
from experiments.pipeline.progress import JobProgress, NullProgress, ProgressSink
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver

logger = logging.getLogger(__name__)


def _persist(
    output_dir: Path,
    job: GenerationJob,
    artifacts: dict[str, str],
    trace: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    """Write artifacts, trace, and metadata for one job into its output folder."""
    for filename, content in artifacts.items():
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    trace_lines = "\n".join(json.dumps(entry) for entry in trace)
    (output_dir / "trace.jsonl").write_text(f"{trace_lines}\n" if trace else "", encoding="utf-8")

    metadata = {
        "job_id": job.job_id,
        "plan_name": job.plan_name,
        "task": job.task,
        "condition": job.condition,
        "item_id": job.item_id,
        "generator_family": job.generator_family,
        "language": job.language,
        "replicate": job.replicate,
        "is_pilot": job.is_pilot,
        "length_range": job.length_range,
        "config": config,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _format_elapsed(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _record(write: Callable[..., None], job_id: str, **fields: Any) -> None:
    """Record one job outcome; a failed write is logged, never allowed to stop the worker."""
    try:
        write(job_id, **fields)
    except Exception:  # the pool must survive a registry write failure
        logger.exception("Could not record outcome for job %s", job_id)


def _announce(progress: JobProgress | None, text: str) -> None:
    """Print a runner line to the job's sink, or to the console if the job has no sink yet."""
    if progress is None:
        print(text, flush=True)  # noqa: T201 — operator-facing progress output
        return
    try:
        progress.line(text)
    except Exception:  # a log-append failure must not stop the worker
        logger.exception("Could not write progress line for %r", text)


def run_job(
    job: GenerationJob,
    resolver: InputResolver,
    runs_dir: Path,
    progress: ProgressSink | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run one job through its backend and persist its output.

    Returns `(output_dir, config)` on success. Raises `JobAbandoned` or
    `JobFailed` after persisting the attempts' evidence to the job's output
    folder, and any other exception for failures the backend did not classify
    (a missing input, an unimplemented backend). The caller (`run_pending`'s
    worker loop) records each outcome against the registry.
    """
    output_dir = runs_dir / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    sink = progress if progress is not None else NullProgress()
    backend = BACKEND_REGISTRY[job.condition]
    input_ref = resolver.resolve(job)
    try:
        result = backend.run(job, input_ref, sink)
    except (JobAbandoned, JobFailed) as exc:
        _persist(output_dir, job, exc.artifacts, exc.trace, exc.config)
        raise
    _persist(output_dir, job, result.artifacts, result.trace, result.config)
    return str(output_dir), result.config


def run_pending(  # noqa: PLR0913, PLR0917 — signature fixed by the runner spec
    registry: Registry,
    plan_name: str,
    resolver: InputResolver,
    runs_dir: Path,
    workers: int,
    item_ids: Collection[str] | None = None,
) -> None:
    """Run every `pending` job for `plan_name`, `workers` at a time.

    `item_ids` limits the run to jobs whose item is listed; an empty set
    matches nothing and the call returns without printing anything.

    Each worker claims one job, runs it, and records the outcome, looping
    until no `pending` jobs remain. A job's own exception is caught and
    recorded (`abandoned` for `JobAbandoned`, `failed` otherwise); it never
    stops the pool or other in-flight jobs.
    """
    total = registry.count_pending(plan_name, item_ids)
    counter = itertools.count(1)
    counter_lock = threading.Lock()

    def _worker_loop() -> None:
        while True:
            job = registry.claim_next_pending(plan_name, item_ids)
            if job is None:
                return
            with counter_lock:
                index = next(counter)
            label = f"[{index}/{total}] {job.item_id}"
            started = time.monotonic()
            progress: JobProgress | None = None
            try:
                job_dir = runs_dir / job.job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                progress = JobProgress(prefix=label, log_path=job_dir / "progress.log")
                progress.line(f"{label} start")
                output_dir, config = run_job(job, resolver, runs_dir, progress)
            except JobAbandoned as exc:
                _record(registry.mark_abandoned, job.job_id, reason=exc.reason, config=exc.config)
                outcome = "abandoned"
            except Exception as exc:  # noqa: BLE001 — one bad job must never stop the pool
                _record(registry.mark_failed, job.job_id, error=str(exc))
                outcome = "failed"
                logger.warning("Job %s failed: %s", job.job_id, exc)
            else:
                _record(registry.mark_done, job.job_id, output_dir=output_dir, config=config)
                outcome = "done"
            elapsed = _format_elapsed(time.monotonic() - started)
            _announce(progress, f"{label} {outcome} ({elapsed})")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_worker_loop) for _ in range(workers)]
        for future in futures:
            future.result()
