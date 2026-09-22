"""Bounded worker pool: claims pending jobs, dispatches to backends, records results.

See spec §8.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from experiments.pipeline.backends import BACKEND_REGISTRY
from experiments.pipeline.models import GenerationJob
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver

logger = logging.getLogger(__name__)


def run_job(job: GenerationJob, resolver: InputResolver, runs_dir: Path) -> tuple[str, dict[str, Any]]:
    """Run one job through its backend and persist its output.

    Returns `(output_dir, config)` on success. Raises on any failure — a
    missing input, a backend not yet implemented, or a model-call error
    all surface the same way here; the caller (`run_pending`'s worker
    loop) is responsible for catching and recording it against the
    registry. Keeping this function ignorant of the registry keeps it
    independently testable.
    """
    backend = BACKEND_REGISTRY[job.condition]
    input_ref = resolver.resolve(job)
    result = backend.run(job, input_ref)

    output_dir = runs_dir / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in result.artifacts.items():
        target = output_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    trace_lines = "\n".join(json.dumps(entry) for entry in result.trace)
    (output_dir / "trace.jsonl").write_text(
        f"{trace_lines}\n" if result.trace else "", encoding="utf-8"
    )

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
        "config": result.config,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return str(output_dir), result.config


def run_pending(
    registry: Registry, plan_name: str, resolver: InputResolver, runs_dir: Path, workers: int
) -> None:
    """Run every `pending` job for `plan_name`, `workers` at a time.

    Each worker claims one job, runs it, and records the outcome, looping
    until no `pending` jobs remain. A job's own exception — including a
    missing input or an unimplemented backend — is caught and recorded as
    `failed`; it never stops the pool or other in-flight jobs.
    """

    def _worker_loop() -> None:
        while True:
            job = registry.claim_next_pending(plan_name)
            if job is None:
                return
            try:
                output_dir, config = run_job(job, resolver, runs_dir)
            except Exception as exc:  # noqa: BLE001 — one bad job must never stop the pool
                registry.mark_failed(job.job_id, error=str(exc))
                logger.warning("Job %s failed: %s", job.job_id, exc)
            else:
                registry.mark_done(job.job_id, output_dir=output_dir, config=config)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_worker_loop) for _ in range(workers)]
        for future in futures:
            future.result()
