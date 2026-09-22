"""Command-line entry point: `python -m experiments.pipeline.cli <command> ...`. See spec §9."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from experiments.pipeline.plan import expand_jobs, load_plan
from experiments.pipeline.registry import Registry
from experiments.pipeline.resolver import InputResolver
from experiments.pipeline.runner import run_pending

DEFAULT_CORPUS_PATH = Path("experiments/data/stories/corpus.parquet")
DEFAULT_DATA_DIR = Path("experiments/data")
DEFAULT_RUNS_DIR = Path("experiments/runs")


def _load_corpus(corpus_path: Path) -> pd.DataFrame:
    return pd.read_parquet(corpus_path)


def _cmd_expand(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    corpus = _load_corpus(args.corpus)
    jobs = expand_jobs(plan, corpus)
    registry = Registry(args.runs_dir / "runs.db")
    try:
        inserted = registry.insert_jobs(jobs)
        print(f"Plan {plan.name!r}: {len(jobs)} jobs described, {inserted} newly inserted.")  # noqa: T201
    finally:
        registry.close()


def _cmd_run(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    corpus = _load_corpus(args.corpus)
    registry = Registry(args.runs_dir / "runs.db")
    try:
        registry.insert_jobs(expand_jobs(plan, corpus))
        resolver = InputResolver(args.data_dir)
        run_pending(registry, plan.name, resolver, args.runs_dir, workers=args.workers)
        print_status(registry, plan.name)
    finally:
        registry.close()


def _cmd_status(args: argparse.Namespace) -> None:
    registry = Registry(args.runs_dir / "runs.db")
    try:
        print_status(registry, args.plan_name)
    finally:
        registry.close()


def print_status(registry: Registry, plan_name: str) -> None:
    """Print job counts by status for `plan_name`."""
    counts = registry.status_counts(plan_name)
    print(f"Plan {plan_name!r}:")  # noqa: T201
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")  # noqa: T201


def _cmd_retry(args: argparse.Namespace) -> None:
    registry = Registry(args.runs_dir / "runs.db")
    try:
        n = registry.requeue_failed(args.plan_name)
        print(f"Requeued {n} failed job(s) for plan {args.plan_name!r}.")  # noqa: T201
    finally:
        registry.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    common.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    common.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)

    parser = argparse.ArgumentParser(
        prog="experiments.pipeline", description="Generation pipeline for the PSALM-SAGA experiments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    expand_parser = subparsers.add_parser("expand", parents=[common])
    expand_parser.add_argument("--plan", type=Path, required=True)
    expand_parser.set_defaults(func=_cmd_expand)

    run_parser = subparsers.add_parser("run", parents=[common])
    run_parser.add_argument("--plan", type=Path, required=True)
    run_parser.add_argument("--workers", type=int, default=1)
    run_parser.set_defaults(func=_cmd_run)

    status_parser = subparsers.add_parser("status", parents=[common])
    status_parser.add_argument("--plan-name", required=True)
    status_parser.set_defaults(func=_cmd_status)

    retry_parser = subparsers.add_parser("retry", parents=[common])
    retry_parser.add_argument("--failed", action="store_true", required=True)
    retry_parser.add_argument("--plan-name", required=True)
    retry_parser.set_defaults(func=_cmd_retry)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for `python -m experiments.pipeline.cli`."""
    args = _parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
