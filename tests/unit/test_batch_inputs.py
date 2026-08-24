"""Tests for `psalm_saga.batch_inputs` — the pure input-resolution logic
`psalm-saga-batch` uses before any agent turn is sent. No model/agent
dependency; everything here works against a `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from psalm_saga.batch_inputs import (
    BatchInputError,
    VariantSource,
    expand_paths,
    resolve_context_inputs,
    resolve_template_inputs,
    resolve_variant_sources,
)


def test_expand_paths_file_passes_through(tmp_path: Path) -> None:
    file_path = tmp_path / "a.txt"
    file_path.write_text("hello")

    assert expand_paths([file_path]) == [file_path]


def test_expand_paths_directory_expands_to_sorted_files(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()  # directories inside are not recursed into

    assert expand_paths([tmp_path]) == [tmp_path / "a.txt", tmp_path / "b.txt"]


def test_expand_paths_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(BatchInputError, match="does not exist"):
        expand_paths([tmp_path / "missing.txt"])


def test_resolve_context_inputs_combines_text_and_files(tmp_path: Path) -> None:
    file_path = tmp_path / "ctx.txt"
    file_path.write_text("from a file")

    result = resolve_context_inputs(["inline text"], [file_path])

    assert result == ["inline text", "from a file"]


def test_resolve_context_inputs_requires_at_least_one_input() -> None:
    with pytest.raises(BatchInputError, match="at least one"):
        resolve_context_inputs([], [])


def test_resolve_template_inputs_reads_files(tmp_path: Path) -> None:
    file_path = tmp_path / "template.md"
    file_path.write_text("## Character\n- brave")

    assert resolve_template_inputs([file_path]) == ["## Character\n- brave"]


def test_resolve_template_inputs_requires_paths() -> None:
    with pytest.raises(BatchInputError, match="at least one"):
        resolve_template_inputs([])


def test_resolve_variant_sources_with_explicit_manifest(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"source": "old-draft.md", "dimensions": ["character"]}]))

    result = resolve_variant_sources([source], manifest)

    assert result == [
        VariantSource(source_path=source, dimensions=("character",), content="once upon a time")
    ]


def test_resolve_variant_sources_with_default_manifest_in_directory(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    (tmp_path / "variant-manifest.json").write_text(
        json.dumps([{"source": "old-draft.md", "dimensions": ["plot-structure"]}])
    )

    result = resolve_variant_sources([tmp_path], None)

    assert result == [
        VariantSource(
            source_path=source, dimensions=("plot-structure",), content="once upon a time"
        )
    ]


def test_resolve_variant_sources_missing_manifest_raises(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")

    with pytest.raises(BatchInputError, match="variant-manifest"):
        resolve_variant_sources([source], None)


def test_resolve_variant_sources_unknown_dimension_raises(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"source": "old-draft.md", "dimensions": ["plot"]}]))

    with pytest.raises(BatchInputError, match="Unknown dimension"):
        resolve_variant_sources([source], manifest)


def test_resolve_variant_sources_source_without_manifest_entry_raises(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    other = tmp_path / "other.md"
    other.write_text("something else")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"source": "old-draft.md", "dimensions": ["character"]}]))

    with pytest.raises(BatchInputError, match="No variant-manifest entry"):
        resolve_variant_sources([source, other], manifest)


def test_resolve_variant_sources_malformed_manifest_json_raises(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not valid json")

    with pytest.raises(BatchInputError, match="Invalid JSON"):
        resolve_variant_sources([source], manifest)


def test_resolve_variant_sources_non_string_source_raises(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"source": 123, "dimensions": ["character"]}]))

    with pytest.raises(BatchInputError, match="'source' must be a string"):
        resolve_variant_sources([source], manifest)


def test_resolve_context_inputs_non_utf8_file_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "binary.txt"
    file_path.write_bytes(b"\xff\xfe\x00\x00invalid")

    with pytest.raises(BatchInputError, match="Not a UTF-8 text file"):
        resolve_context_inputs([], [file_path])
