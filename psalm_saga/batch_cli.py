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

from psalm_saga.batch_inputs import (
    VariantSource,
    resolve_context_inputs,
    resolve_template_inputs,
    resolve_variant_sources,
)

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
    parser.add_argument("--session", dest="session_id", default=None)
    parser.add_argument("--model", dest="model", default=None)
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
                {"source": str(source.source_path), "dimensions": list(source.dimensions)}
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
