"""Input resolution for `psalm-saga-batch`: turning CLI-supplied paths and
manifests into the concrete content each generation mode needs, before any
agent turn is sent.

Kept free of any model/agent/session dependency so it's cheaply unit
testable against a `tmp_path` — see `docs/superpowers/specs/
2026-08-24-batch-story-generation-design.md` for the CLI surface this
supports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DIMENSION_SLUGS = frozenset(
    {
        "writing-style",
        "narrative-voice",
        "character",
        "plot-structure",
        "scene-sequence",
        "world-building",
    }
)

DEFAULT_VARIANT_MANIFEST_NAME = "variant-manifest.json"


class BatchInputError(ValueError):
    """Raised for any invalid combination of batch CLI input arguments."""


@dataclass(frozen=True)
class VariantSource:
    """One source file and the dimension(s) that should change for it."""

    source_path: Path
    dimensions: tuple[str, ...]
    content: str


def _read_text_or_raise(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BatchInputError(f"Not a UTF-8 text file: {file_path}") from exc


def expand_paths(paths: list[Path]) -> list[Path]:
    """Expand a list of file-or-directory paths into a flat list of files.

    A file passes through unchanged, in the given order. A directory
    expands to every file directly inside it (non-recursive), sorted for
    deterministic ordering. Raises `BatchInputError` if a given path
    doesn't exist.
    """
    resolved: list[Path] = []
    for path in paths:
        if not path.exists():
            raise BatchInputError(f"Input path does not exist: {path}")
        if path.is_dir():
            resolved.extend(sorted(p for p in path.iterdir() if p.is_file()))
        else:
            resolved.append(path)
    return resolved


def resolve_context_inputs(texts: list[str], paths: list[Path]) -> list[str]:
    """Combine inline `--context` text with the contents of `--context-path`
    files/directories into one flat list of inspiration strings.

    Raises `BatchInputError` if neither `texts` nor `paths` supplied any
    content at all.
    """
    combined = list(texts)
    for file_path in expand_paths(paths):
        combined.append(_read_text_or_raise(file_path))
    if not combined:
        msg = "--mode context requires at least one --context TEXT or --context-path PATH"
        raise BatchInputError(msg)
    return combined


def resolve_template_inputs(paths: list[Path]) -> list[str]:
    """Read every `--template-path` file/directory into a flat list of
    template document contents.

    Raises `BatchInputError` if no paths were supplied.
    """
    if not paths:
        msg = "--mode template requires at least one --template-path PATH"
        raise BatchInputError(msg)
    return [_read_text_or_raise(file_path) for file_path in expand_paths(paths)]


def _load_manifest_file(manifest_path: Path) -> dict[str, list[str]]:
    if not manifest_path.is_file():
        raise BatchInputError(f"Variant manifest not found: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BatchInputError(f"Invalid JSON in variant manifest {manifest_path}: {exc}") from exc
    if not isinstance(raw, list):
        raise BatchInputError(f"Variant manifest must be a JSON array: {manifest_path}")

    entries: dict[str, list[str]] = {}
    for entry in raw:
        if not isinstance(entry, dict) or "source" not in entry or "dimensions" not in entry:
            raise BatchInputError(
                f"Each variant manifest entry needs 'source' and 'dimensions': {manifest_path}"
            )
        dimensions = entry["dimensions"]
        if not isinstance(dimensions, list) or not dimensions:
            raise BatchInputError(f"'dimensions' must be a non-empty list: {entry}")
        for dimension in dimensions:
            if dimension not in DIMENSION_SLUGS:
                raise BatchInputError(
                    f"Unknown dimension {dimension!r} in {manifest_path}. "
                    f"Valid dimensions: {sorted(DIMENSION_SLUGS)}"
                )
        source_value = entry["source"]
        if not isinstance(source_value, str):
            raise BatchInputError(f"'source' must be a string in {manifest_path}: {entry}")
        # Resolve the manifest's own "source" value relative to the
        # manifest file's directory, matching how a human would write one
        # by hand next to the sources it describes.
        resolved_source = (manifest_path.parent / source_value).resolve()
        entries[str(resolved_source)] = list(dimensions)
    return entries


def resolve_variant_sources(
    source_paths: list[Path], manifest_path: Path | None
) -> list[VariantSource]:
    """Resolve `--source-path`/`--variant-manifest` into one `VariantSource`
    per source file, each carrying the dimension(s) to vary for it.

    `--mode variant` never infers dimensions on its own (see the design
    doc) — every resolved source file must have a manifest entry, whether
    from an explicit `--variant-manifest` or a `variant-manifest.json`
    found inside one of the given source directories. Raises
    `BatchInputError` if no manifest can be found, or if any resolved
    source file has no matching entry.
    """
    if not source_paths:
        msg = "--mode variant requires at least one --source-path PATH"
        raise BatchInputError(msg)

    manifest_entries: dict[str, list[str]] = {}
    if manifest_path is not None:
        manifest_entries = _load_manifest_file(manifest_path)
    else:
        for path in source_paths:
            if path.is_dir():
                candidate = path / DEFAULT_VARIANT_MANIFEST_NAME
                if candidate.is_file():
                    manifest_entries.update(_load_manifest_file(candidate))
        if not manifest_entries:
            raise BatchInputError(
                "--mode variant requires --variant-manifest, or a "
                f"{DEFAULT_VARIANT_MANIFEST_NAME} file inside a given --source-path directory"
            )

    # The default-manifest file itself (when found inside a source
    # directory) is metadata, not a story source — exclude it from the
    # expanded file list either way.
    files = [
        file_path
        for file_path in expand_paths(source_paths)
        if file_path.name != DEFAULT_VARIANT_MANIFEST_NAME
    ]

    sources: list[VariantSource] = []
    for file_path in files:
        key = str(file_path.resolve())
        if key not in manifest_entries:
            raise BatchInputError(f"No variant-manifest entry for source file: {file_path}")
        sources.append(
            VariantSource(
                source_path=file_path,
                dimensions=tuple(manifest_entries[key]),
                content=_read_text_or_raise(file_path),
            )
        )
    return sources
