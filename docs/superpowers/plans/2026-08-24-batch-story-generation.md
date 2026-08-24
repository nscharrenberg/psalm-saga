# Batch Story Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `psalm-saga-batch` command that generates many complete stories in one session with no human interaction, across four input modes (scratch, context, template, variant), reusing the existing interactive pipeline's subagent architecture.

**Architecture:** A new console script (`psalm_saga/batch_cli.py`) builds one agent per batch session (same `build_agent`/session/subagent wiring as the interactive CLI) with a new `batch-story-generation` skill force-injected as its bootstrap instead of `using-psalm-saga`. The CLI loops, sending one per-story instruction message on the same thread; the orchestrator runs each story through the same spec → plan → draft → review pipeline, but new "Autonomous Mode" sections in `story-brainstorming`, `writing-story-plans`, and `reviewing-story-dimensions` replace "ask/wait for sign-off" with "decide/self-approve" whenever that bootstrap is active. `chapter-writer` and `dimension-reviewer` subagent dispatch is unchanged. Finished stories are promoted (copied) from `docs/drafts/<story_name>/` to `docs/stories/<story_name>/`; the CLI's loop trusts only the filesystem (`docs/stories/` contents), never the model's own claims, to decide when it's done.

**Tech Stack:** Python 3.14+, `deepagents`/LangChain/LangGraph (existing), `argparse`, `json`, `shutil`, `pathlib` (stdlib only — no new dependencies), `pytest` for tests.

**Spec:** `docs/superpowers/specs/2026-08-24-batch-story-generation-design.md`

## Global Constraints

- Batch sessions use `docs/drafts/<story_name>/` (work in progress) and `docs/stories/<story_name>/` (finished) under `sessions/<session_id>/`. Interactive sessions' existing `docs/psalm-saga/<slug>-*.md` layout must not change.
- `--mode variant` always runs as `--combine separate`; `--combine mixed` is a validation error for that mode.
- `--mode variant` never infers which dimensions to vary on its own — an explicit `--variant-manifest` (or a `variant-manifest.json` found inside a given `--source-path` directory) is always required.
- The three "Autonomous Mode" additions to existing skills are only active when `batch-story-generation` is the force-injected bootstrap for the session; default interactive behavior (asking, waiting for sign-off, asking about ambiguous `Partial` findings) must be provably unchanged for `psalm-saga` sessions.
- Fix-loop cap: 3 total attempts per chapter (1 in-context fix + 2 fresh `chapter-writer` redispatches) before a story is abandoned rather than promoted with unresolved findings.
- `--count` is the target *total* number of stories in `docs/stories/` for the session; re-running against an existing session only generates the remainder.
- Follow the repo's `ruff` config (line-length 100, `select = ["ALL"]` with the ignores in `pyproject.toml`) and existing docstring/type-hint conventions (Google-style docstrings, full type hints, `from __future__ import annotations` in new modules where the existing codebase uses it).
- No new third-party dependencies — everything needed (`argparse`, `json`, `shutil`, `pathlib`) is stdlib; `rich`, `python-dotenv` are already dependencies.

---

### Task 1: Input resolution (`batch_inputs.py`)

**Files:**
- Create: `psalm_saga/batch_inputs.py`
- Test: `tests/unit/test_batch_inputs.py`

**Interfaces:**
- Produces: `BatchInputError(ValueError)`; `VariantSource` (frozen dataclass: `source_path: Path`, `dimensions: tuple[str, ...]`); `DIMENSION_SLUGS: frozenset[str]`; `DEFAULT_VARIANT_MANIFEST_NAME: str`; `expand_paths(paths: list[Path]) -> list[Path]`; `resolve_context_inputs(texts: list[str], paths: list[Path]) -> list[str]`; `resolve_template_inputs(paths: list[Path]) -> list[str]`; `resolve_variant_sources(source_paths: list[Path], manifest_path: Path | None) -> list[VariantSource]`. `batch_cli.py` (Task 10) consumes all of these.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_batch_inputs.py`:

```python
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

    assert result == [VariantSource(source_path=source, dimensions=("character",))]


def test_resolve_variant_sources_with_default_manifest_in_directory(tmp_path: Path) -> None:
    source = tmp_path / "old-draft.md"
    source.write_text("once upon a time")
    (tmp_path / "variant-manifest.json").write_text(
        json.dumps([{"source": "old-draft.md", "dimensions": ["plot-structure"]}])
    )

    result = resolve_variant_sources([tmp_path], None)

    assert result == [VariantSource(source_path=source, dimensions=("plot-structure",))]


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_batch_inputs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psalm_saga.batch_inputs'`

- [ ] **Step 3: Write the implementation**

Create `psalm_saga/batch_inputs.py`:

```python
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
        combined.append(file_path.read_text(encoding="utf-8"))
    if not combined:
        raise BatchInputError(
            "--mode context requires at least one --context TEXT or --context-path PATH"
        )
    return combined


def resolve_template_inputs(paths: list[Path]) -> list[str]:
    """Read every `--template-path` file/directory into a flat list of
    template document contents.

    Raises `BatchInputError` if no paths were supplied.
    """
    if not paths:
        raise BatchInputError("--mode template requires at least one --template-path PATH")
    return [file_path.read_text(encoding="utf-8") for file_path in expand_paths(paths)]


def _load_manifest_file(manifest_path: Path) -> dict[str, list[str]]:
    if not manifest_path.is_file():
        raise BatchInputError(f"Variant manifest not found: {manifest_path}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        # Resolve the manifest's own "source" value relative to the
        # manifest file's directory, matching how a human would write one
        # by hand next to the sources it describes.
        resolved_source = (manifest_path.parent / entry["source"]).resolve()
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
        raise BatchInputError("--mode variant requires at least one --source-path PATH")

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
            VariantSource(source_path=file_path, dimensions=tuple(manifest_entries[key]))
        )
    return sources
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_batch_inputs.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/batch_inputs.py tests/unit/test_batch_inputs.py
git commit -m "feat(batch): add input resolution for context/template/variant modes"
```

---

### Task 2: Directory layout & promotion (`batch_session.py`)

**Files:**
- Create: `psalm_saga/batch_session.py`
- Test: `tests/unit/test_batch_session.py`

**Interfaces:**
- Consumes: `psalm_saga.session.session_directory(settings, session_id) -> Path` (existing); `psalm_saga.settings.Settings` (existing).
- Produces: `drafts_dir`, `stories_dir`, `story_draft_dir`, `story_final_dir`, `existing_story_names`, `promoted_story_count`, `promote_story` (all `(settings: Settings, session_id: str, ...) -> Path | set[str] | int`). Consumed by `batch_cli.py` (Tasks 10-11).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_batch_session.py`:

```python
"""Tests for `psalm_saga.batch_session` — directory layout, name
bookkeeping, and promotion for `psalm-saga-batch` sessions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.batch_session import (
    drafts_dir,
    existing_story_names,
    promote_story,
    promoted_story_count,
    stories_dir,
    story_draft_dir,
    story_final_dir,
)
from psalm_saga.session import session_directory
from psalm_saga.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def test_drafts_and_stories_dir_paths(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert drafts_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "drafts"
    assert stories_dir(settings, "session-1") == session_directory(settings, "session-1") / "docs" / "stories"


def test_existing_story_names_empty_when_nothing_exists(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert existing_story_names(settings, "session-1") == set()


def test_existing_story_names_combines_drafts_and_stories(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    story_draft_dir(settings, "session-1", "draft-only").mkdir(parents=True)
    story_final_dir(settings, "session-1", "finished-one").mkdir(parents=True)

    assert existing_story_names(settings, "session-1") == {"draft-only", "finished-one"}


def test_promoted_story_count(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    story_final_dir(settings, "session-1", "story-a").mkdir(parents=True)
    story_final_dir(settings, "session-1", "story-b").mkdir(parents=True)

    assert promoted_story_count(settings, "session-1") == 2


def test_promote_story_copies_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    draft.mkdir(parents=True)
    (draft / "story-a-spec.md").write_text("spec content")

    final = promote_story(settings, "session-1", "story-a")

    assert final == story_final_dir(settings, "session-1", "story-a")
    assert (final / "story-a-spec.md").read_text() == "spec content"


def test_promote_story_missing_draft_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with pytest.raises(FileNotFoundError):
        promote_story(settings, "session-1", "missing")


def test_promote_story_already_promoted_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    draft = story_draft_dir(settings, "session-1", "story-a")
    draft.mkdir(parents=True)
    story_final_dir(settings, "session-1", "story-a").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        promote_story(settings, "session-1", "story-a")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_batch_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psalm_saga.batch_session'`

- [ ] **Step 3: Write the implementation**

Create `psalm_saga/batch_session.py`:

```python
"""Directory layout, name bookkeeping, and promotion logic for
`psalm-saga-batch` sessions.

Batch sessions use `docs/drafts/<story_name>/` for work in progress and
`docs/stories/<story_name>/` for finished stories, instead of interactive
sessions' `docs/psalm-saga/<slug>-*.md` convention — see the design doc's
"Directory layout & session semantics" section. Every function here takes
the same `(settings, session_id)` pair `psalm_saga.session` uses, so a
batch session is just a normal session with a different `docs/` shape.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from psalm_saga.session import session_directory
from psalm_saga.settings import Settings

DRAFTS_DIRNAME = "drafts"
STORIES_DIRNAME = "stories"
DOCS_DIRNAME = "docs"


def drafts_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/drafts/` — every story's working directory."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / DRAFTS_DIRNAME


def stories_dir(settings: Settings, session_id: str) -> Path:
    """`sessions/<session_id>/docs/stories/` — every finished story."""
    return session_directory(settings, session_id) / DOCS_DIRNAME / STORIES_DIRNAME


def story_draft_dir(settings: Settings, session_id: str, story_name: str) -> Path:
    """This story's working directory under `drafts_dir`."""
    return drafts_dir(settings, session_id) / story_name


def story_final_dir(settings: Settings, session_id: str, story_name: str) -> Path:
    """This story's promoted directory under `stories_dir`."""
    return stories_dir(settings, session_id) / story_name


def _dir_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {entry.name for entry in directory.iterdir() if entry.is_dir()}


def existing_story_names(settings: Settings, session_id: str) -> set[str]:
    """Every story name already claimed in this session, promoted or not.

    Passed into each per-story instruction so the model never reuses a
    name already used by an earlier story in the same batch run.
    """
    return _dir_names(drafts_dir(settings, session_id)) | _dir_names(
        stories_dir(settings, session_id)
    )


def promoted_story_count(settings: Settings, session_id: str) -> int:
    """How many stories have actually been promoted to `docs/stories/`.

    This is the ground truth `batch_cli`'s main loop checks against
    `--count` — it never trusts the agent's own claim of success, only
    what's actually on disk.
    """
    return len(_dir_names(stories_dir(settings, session_id)))


def promote_story(settings: Settings, session_id: str, story_name: str) -> Path:
    """Copy a finished story's draft directory to its final location.

    Raises `FileNotFoundError` if the draft directory doesn't exist, and
    `FileExistsError` if the final directory already exists (promotion
    should only ever happen once per story name).
    """
    draft = story_draft_dir(settings, session_id, story_name)
    if not draft.is_dir():
        raise FileNotFoundError(f"No draft directory for story {story_name!r}: {draft}")
    final = story_final_dir(settings, session_id, story_name)
    shutil.copytree(draft, final)
    return final
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_batch_session.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/batch_session.py tests/unit/test_batch_session.py
git commit -m "feat(batch): add drafts/stories directory layout and promotion"
```

---

### Task 3: Generalize `bootstrap.py` for an alternate bootstrap skill

**Files:**
- Modify: `psalm_saga/bootstrap.py`
- Test: `tests/unit/test_bootstrap.py`

**Interfaces:**
- Produces: `BATCH_BOOTSTRAP_SKILL: str = "batch-story-generation"`; `build_bootstrap(skills_dir=SKILLS_DIR, *, bootstrap_skill: str = BOOTSTRAP_SKILL) -> str` (new `bootstrap_skill` kwarg, default preserves current behavior); `build_batch_bootstrap(skills_dir=SKILLS_DIR) -> str`; `compose_system_prompt(application_prompt="", skills_dir=SKILLS_DIR, *, bootstrap_skill: str = BOOTSTRAP_SKILL) -> str` (new kwarg, default unchanged); `compose_batch_system_prompt(application_prompt="", skills_dir=SKILLS_DIR) -> str`. Consumed by `agent.py` (Task 4) and `batch_cli.py` (Task 11).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_bootstrap.py`:

```python
"""Tests for `psalm_saga.bootstrap`'s `bootstrap_skill` override — the
mechanism `psalm-saga-batch` uses to force-inject `batch-story-generation`
instead of `using-psalm-saga` for a batch session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.bootstrap import (
    BATCH_BOOTSTRAP_SKILL,
    BOOTSTRAP_SKILL,
    build_batch_bootstrap,
    build_bootstrap,
    compose_batch_system_prompt,
    compose_system_prompt,
)


def _write_skill(skills_dir: Path, name: str, body: str) -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n\n{body}\n")


def test_build_bootstrap_defaults_to_using_psalm_saga(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = build_bootstrap(tmp_path)

    assert "Interactive body." in result
    assert "Batch body." not in result


def test_build_bootstrap_honors_bootstrap_skill_override(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = build_bootstrap(tmp_path, bootstrap_skill=BATCH_BOOTSTRAP_SKILL)

    assert "Batch body." in result
    assert "Interactive body." not in result


def test_build_batch_bootstrap_matches_explicit_override(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    assert build_batch_bootstrap(tmp_path) == build_bootstrap(
        tmp_path, bootstrap_skill=BATCH_BOOTSTRAP_SKILL
    )


def test_build_bootstrap_missing_skill_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_bootstrap(tmp_path, bootstrap_skill="does-not-exist")


def test_compose_batch_system_prompt_prepends_application_prompt(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")
    _write_skill(tmp_path, BATCH_BOOTSTRAP_SKILL, "Batch body.")

    result = compose_batch_system_prompt("My app prompt.", tmp_path)

    assert result.startswith("My app prompt.")
    assert "Batch body." in result


def test_compose_system_prompt_default_behavior_unchanged(tmp_path: Path) -> None:
    _write_skill(tmp_path, BOOTSTRAP_SKILL, "Interactive body.")

    result = compose_system_prompt(skills_dir=tmp_path)

    assert "Interactive body." in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_bootstrap.py -v`
Expected: FAIL with `ImportError: cannot import name 'BATCH_BOOTSTRAP_SKILL'`

- [ ] **Step 3: Rewrite the implementation**

Replace the full contents of `psalm_saga/bootstrap.py`:

```python
"""Assembles the psalm-saga bootstrap for a deepagents `system_prompt`.

Why this module exists
-----------------------
deepagents' own `SkillsMiddleware` only ever surfaces a skill's *name* and
*description* in the system prompt at startup (progressive disclosure); the
full body of a skill is loaded on demand via `read_file`. That's fine for
ordinary skills, but `using-psalm-saga` is special: it's the
behavior-shaping bootstrap that teaches the model the spec-first workflow
exists at all and that it must be followed *before* doing anything else,
including asking a clarifying question. Leaving that to chance (an entry in
a skill list the model might not read closely) is a much weaker guarantee
than force-injecting it.

`psalm-saga-batch` needs the same guarantee for a different bootstrap:
`batch-story-generation` (see `psalm_saga/skills/batch-story-generation/`),
which replaces `using-psalm-saga`'s human-dialogue framing entirely for a
batch session. `build_bootstrap`/`compose_system_prompt` both accept a
`bootstrap_skill` override for this; the batch-specific
`build_batch_bootstrap`/`compose_batch_system_prompt` wrappers are the
convenience form `batch_cli.py` actually calls.

This module reads the real `SKILL.md` off disk for whichever skill is the
active bootstrap, strips its YAML frontmatter, appends the shared
tool-mapping reference, and returns a single string meant to be
concatenated onto the application's own `system_prompt` before calling
`create_deep_agent(...)`.

This is *not* a copy of any skill's content baked into this file — it
reads the real files at call time, so editing the vendored `skills/`
directory automatically changes what gets injected, with zero edits here.
"""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
BOOTSTRAP_SKILL = "using-psalm-saga"
BATCH_BOOTSTRAP_SKILL = "batch-story-generation"
TOOL_MAPPING_PATH = "references/deepagents-tools.md"

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _build_preamble(bootstrap_skill: str) -> str:
    return (
        "<EXTREMELY_IMPORTANT>\n"
        f"The `{bootstrap_skill}` skill below is already active for this "
        "conversation — it was injected here at agent-construction time. Do "
        f"not try to read or invoke `{bootstrap_skill}` again; it is not a "
        "step you need to take. Every *other* skill it mentions still follows "
        'the normal progressive-disclosure flow: check the "Skills System" '
        "section of this prompt for what's available, and `read_file` a "
        "skill's `SKILL.md` when it applies.\n"
        "</EXTREMELY_IMPORTANT>\n"
    )


def _strip_frontmatter(skill_md_text: str) -> str:
    """Remove the YAML frontmatter block from a SKILL.md's raw text."""
    return _FRONTMATTER_RE.sub("", skill_md_text, count=1).strip()


def build_bootstrap(
    skills_dir: str | Path = SKILLS_DIR, *, bootstrap_skill: str = BOOTSTRAP_SKILL
) -> str:
    """Return the psalm-saga bootstrap fragment for a deepagents `system_prompt`.

    Args:
        skills_dir: Path to the vendored `skills/` directory (defaults to
            the one shipped alongside this package). Point this at your own
            copy if you've forked or extended the skills separately.
        bootstrap_skill: Which skill's `SKILL.md` to force-inject as the
            bootstrap. Defaults to `using-psalm-saga` (interactive mode);
            pass `BATCH_BOOTSTRAP_SKILL` for a `psalm-saga-batch` session.
            The tool-name mapping reference is always read from
            `using-psalm-saga`'s `references/deepagents-tools.md`
            regardless of this argument — it documents the harness's
            generic tool names, not anything specific to either bootstrap
            skill's own prose.

    Raises:
        FileNotFoundError: if `<bootstrap_skill>/SKILL.md` is missing from
            `skills_dir` — this fails loudly rather than silently shipping
            an agent with no bootstrap.

    """
    skills_dir = Path(skills_dir)
    skill_md_path = skills_dir / bootstrap_skill / "SKILL.md"
    tool_mapping_path = skills_dir / BOOTSTRAP_SKILL / TOOL_MAPPING_PATH

    if not skill_md_path.is_file():
        raise FileNotFoundError(
            f"{bootstrap_skill}/SKILL.md not found under {skills_dir}. "
            "Did you vendor the skills/ directory correctly?"
        )

    body = _strip_frontmatter(skill_md_path.read_text(encoding="utf-8"))

    tool_mapping_section = ""
    if tool_mapping_path.is_file():
        tool_mapping = tool_mapping_path.read_text(encoding="utf-8").strip()
        tool_mapping_section = (
            f"\n\n## Tool mapping for this harness (LangChain Deep Agents)\n\n{tool_mapping}\n"
        )

    return f"{_build_preamble(bootstrap_skill)}\n{body}{tool_mapping_section}"


def build_batch_bootstrap(skills_dir: str | Path = SKILLS_DIR) -> str:
    """`build_bootstrap`, forcing `batch-story-generation` as the bootstrap skill."""
    return build_bootstrap(skills_dir, bootstrap_skill=BATCH_BOOTSTRAP_SKILL)


def compose_system_prompt(
    application_prompt: str = "",
    skills_dir: str | Path = SKILLS_DIR,
    *,
    bootstrap_skill: str = BOOTSTRAP_SKILL,
) -> str:
    """Concatenate the caller's own instructions with the psalm-saga bootstrap.

    `using-psalm-saga`'s own text notes user instructions take precedence
    over skills, which override default behavior — so the application's
    prompt goes first, the bootstrap after, matching that precedence order.
    """
    bootstrap = build_bootstrap(skills_dir, bootstrap_skill=bootstrap_skill)
    if not application_prompt.strip():
        return bootstrap
    return f"{application_prompt.strip()}\n\n{bootstrap}"


def compose_batch_system_prompt(
    application_prompt: str = "",
    skills_dir: str | Path = SKILLS_DIR,
) -> str:
    """`compose_system_prompt`, forcing `batch-story-generation` as the bootstrap skill."""
    return compose_system_prompt(
        application_prompt, skills_dir, bootstrap_skill=BATCH_BOOTSTRAP_SKILL
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bootstrap.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full unit suite to confirm no regressions**

Run: `uv run pytest tests/unit -v`
Expected: PASS (all existing tests still pass — `build_bootstrap()`/`compose_system_prompt()` called with no new arguments behave identically to before)

- [ ] **Step 6: Commit**

```bash
git add psalm_saga/bootstrap.py tests/unit/test_bootstrap.py
git commit -m "feat(bootstrap): support an alternate bootstrap skill for batch mode"
```

---

### Task 4: Thread `bootstrap_skill` through `build_agent`

**Files:**
- Modify: `psalm_saga/agent.py`
- Modify: `tests/unit/test_agent_wiring.py`

**Interfaces:**
- Consumes: `BOOTSTRAP_SKILL`, `compose_system_prompt` from `psalm_saga.bootstrap` (Task 3).
- Produces: `build_agent(..., bootstrap_skill: str = BOOTSTRAP_SKILL, **create_deep_agent_kwargs)` — new keyword-only-by-convention param (existing signature already uses `*` before other keyword args). Consumed by `batch_cli.py` (Task 11).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_agent_wiring.py` (add this function; keep the existing three):

```python
def test_build_agent_forwards_bootstrap_skill_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(agent_module, "init_chat_model", lambda *, model, **_kw: f"stub:{model}")
    monkeypatch.setattr(agent_module, "create_deep_agent", lambda **kwargs: "stub-compiled-graph")

    captured: dict[str, Any] = {}

    def fake_compose_system_prompt(*, application_prompt: str, bootstrap_skill: str) -> str:
        captured["bootstrap_skill"] = bootstrap_skill
        return "stub-system-prompt"

    monkeypatch.setattr(agent_module, "compose_system_prompt", fake_compose_system_prompt)

    settings = Settings()
    settings.backend.root_dir = tmp_path
    agent_module.build_agent(settings, bootstrap_skill="batch-story-generation")

    assert captured["bootstrap_skill"] == "batch-story-generation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_wiring.py::test_build_agent_forwards_bootstrap_skill_override -v`
Expected: FAIL with `TypeError: build_agent() got an unexpected keyword argument 'bootstrap_skill'`

- [ ] **Step 3: Implement**

In `psalm_saga/agent.py`, change the import line:

```python
from psalm_saga.bootstrap import SKILLS_DIR, compose_system_prompt
```

to:

```python
from psalm_saga.bootstrap import BOOTSTRAP_SKILL, SKILLS_DIR, compose_system_prompt
```

Change the `build_agent` signature from:

```python
def build_agent(  # noqa: PLR0913
    settings: Settings | None = None,
    *,
    session_id: str | None = None,
    tools: Sequence[Any] | None = None,
    system_prompt: str = "",
    subagents: Sequence[SubAgent] | None = None,
    checkpointer: Any = None,
    **create_deep_agent_kwargs: Any,
):
```

to:

```python
def build_agent(  # noqa: PLR0913
    settings: Settings | None = None,
    *,
    session_id: str | None = None,
    tools: Sequence[Any] | None = None,
    system_prompt: str = "",
    subagents: Sequence[SubAgent] | None = None,
    checkpointer: Any = None,
    bootstrap_skill: str = BOOTSTRAP_SKILL,
    **create_deep_agent_kwargs: Any,
):
```

Add a docstring `Args:` entry after the `system_prompt` entry:

```
        bootstrap_skill: Which skill's `SKILL.md` to force-inject as the
            bootstrap. Defaults to `using-psalm-saga` (interactive mode).
            `batch_cli.py` passes `psalm_saga.bootstrap.BATCH_BOOTSTRAP_SKILL`
            here for a `psalm-saga-batch` session.
```

Change the line:

```python
    full_system_prompt = compose_system_prompt(application_prompt=system_prompt)
```

to:

```python
    full_system_prompt = compose_system_prompt(
        application_prompt=system_prompt, bootstrap_skill=bootstrap_skill
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_agent_wiring.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/agent.py tests/unit/test_agent_wiring.py
git commit -m "feat(agent): allow build_agent to override the bootstrap skill"
```

---

### Task 5: New skill `batch-story-generation`

**Files:**
- Create: `psalm_saga/skills/batch-story-generation/SKILL.md`
- Modify: `tests/unit/test_bootstrap.py`

**Interfaces:**
- Consumes: `build_batch_bootstrap()` (Task 3), reading the real `SKILLS_DIR`.
- Produces: the on-disk skill `batch-story-generation`, referenced by `BATCH_BOOTSTRAP_SKILL` and by name from the Autonomous Mode sections added in Tasks 6-8.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_bootstrap.py`:

```python
def test_build_batch_bootstrap_against_real_skills_dir() -> None:
    result = build_batch_bootstrap()

    assert "batch-story-generation" in result
    assert "psalm-saga-batch" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bootstrap.py::test_build_batch_bootstrap_against_real_skills_dir -v`
Expected: FAIL with `FileNotFoundError: batch-story-generation/SKILL.md not found under ...`

- [ ] **Step 3: Write the skill**

Create `psalm_saga/skills/batch-story-generation/SKILL.md`:

```markdown
---
name: batch-story-generation
description: Force-injected as the bootstrap only by the psalm-saga-batch command - runs the full spec-to-final-story pipeline for one story at a time with no human interaction, deciding every dimension itself under one of four input modes (scratch, context, template, variant), and never asking a question.
---

# Batch Story Generation

<INTERACTIVE-SESSION-STOP>
This skill is force-injected as the active bootstrap only by the
`psalm-saga-batch` command, replacing `using-psalm-saga` for that session
entirely. If you are having a normal conversation with a human in an
interactive `psalm-saga` session, ignore this skill — it does not apply,
and you should be following `using-psalm-saga` (which asks questions and
waits for sign-off) instead.
</INTERACTIVE-SESSION-STOP>

<EXTREMELY-IMPORTANT>
You will never see a human response in this session. Every decision a
human would normally make in `story-brainstorming`, `writing-story-plans`,
or `reviewing-story-dimensions` — every dimension, every sign-off, every
judgement call on an ambiguous review finding — is yours to make. Do not
ask a question and wait; decide, write it down, and keep going.
</EXTREMELY-IMPORTANT>

## What you'll receive

The CLI sends one instruction message per story, on this same session
thread, shaped like:

> Generate story {i} of {count}. Mode: {scratch|context|template|variant}.
> Inputs: [...]. Combine: {mixed|separate}. Existing names in this
> session: [...].

Generate exactly the one story that message describes, then stop — end
your turn with a short summary (story name, whether it was promoted or
abandoned, and why). The CLI's own loop decides whether and how to ask for
the next one; do not generate more than one story per instruction message.

## The pipeline, per story

Every story still goes through the same four stages interactive sessions
do — batch mode changes who decides and whether there's a pause, not
whether the process happens:

1. **Autonomous brainstorming** — invoke `story-brainstorming`, following
   its `## Autonomous Mode` section, which covers all four input modes
   (scratch/context/template/variant) in detail. Produces
   `docs/drafts/<story_name>/<story_name>-spec.md`.
2. **Autonomous planning** — invoke `writing-story-plans`, following its
   `## Autonomous Mode` section. Produces
   `docs/drafts/<story_name>/<story_name>-plan.md`.
3. **Drafting** — invoke `drafting-chapters` exactly as written; it is
   unchanged for batch mode. Dispatches the `chapter-writer` subagent per
   chapter, same as an interactive session.
4. **Autonomous review-and-fix** — invoke `reviewing-story-dimensions`,
   following its `## Autonomous Mode` section, per chapter and once for
   the whole story. Produces/updates
   `docs/drafts/<story_name>/<story_name>-review.md`.
5. **Promote** — once the whole-story review is fully clean, copy
   `docs/drafts/<story_name>/` to `docs/stories/<story_name>/`. If the
   review never converges (see the fix-loop cap in
   `reviewing-story-dimensions`'s Autonomous Mode), do not promote — leave
   the draft as an abandoned record and say so in your final summary.

<EXTREMELY-IMPORTANT>
Brainstorming and planning still happen directly in your own turn, never
dispatched to a subagent — the reasoning is the same as in interactive
mode (a dispatched subagent can't carry context back into this
conversation for the next stage), it just no longer depends on needing a
human to talk to. `chapter-writer` and `dimension-reviewer` remain the
only subagents this pipeline ever dispatches, exactly as in interactive
mode.
</EXTREMELY-IMPORTANT>

## Story naming

Pick a kebab-case `story_name` from the story's own premise once you've
settled on one (same convention interactive sessions use for `<slug>`).
Check it against the "Existing names in this session" list the CLI gave
you — if it collides, pick a different one before writing any file.

## Diversity across a batch

Before locking a scratch-mode premise, and as a light sanity check for the
other modes too, read `docs/drafts/_batch-log.md` if it exists (there is
none for the first story of a session). It's a plain running log, one line
per story: `<story_name>: <genre> / <narrative voice> / <one-line
premise>`. If your new story's combination reads as a near-duplicate of an
existing line (same genre, same narrative voice, same core conflict
shape), reroll before locking anything. After promoting (or abandoning)
this story, append its own line.

## Red Flags

| Thought | Reality |
|---------|---------|
| "This dimension is ambiguous, I'll leave a note and move on" | There's no one to resolve it later. Pick a concrete answer yourself, document the reasoning inline, and proceed. |
| "I'll dispatch a subagent to do the brainstorming for this story, it's faster" | Still no — subagents can't carry state into your next pipeline stage, whether or not a human is involved. Do it inline. |
| "This review finding is only Partial, batch mode can let that slide" | Autonomous Mode treats Partial the same as Missing — see `reviewing-story-dimensions`. Fix it or abandon the story; never promote it as-is. |
| "I've generated 3 stories already, this 4th one can reuse the same voice, it's fine" | Check `_batch-log.md` first. A batch is supposed to be diverse, not ten variations on the same idea. |
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bootstrap.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/batch-story-generation/SKILL.md tests/unit/test_bootstrap.py
git commit -m "feat(skills): add batch-story-generation bootstrap skill"
```

---

### Task 6: Autonomous Mode section in `story-brainstorming`

**Files:**
- Modify: `psalm_saga/skills/story-brainstorming/SKILL.md`
- Create: `tests/unit/test_skill_content.py`

**Interfaces:**
- Produces: a `## Autonomous Mode` section in `story-brainstorming/SKILL.md`, referenced from `batch-story-generation` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_skill_content.py`:

```python
"""Lightweight regression checks that the batch-mode "Autonomous Mode"
sections added to the interactive skills are actually present on disk.
Not a substitute for the eval-based behavioral checks in tests/evals/ —
just a guard against a section being accidentally deleted or renamed.
"""

from __future__ import annotations

from psalm_saga.bootstrap import SKILLS_DIR


def _read_skill(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def test_story_brainstorming_has_autonomous_mode_section() -> None:
    body = _read_skill("story-brainstorming")

    assert "## Autonomous Mode" in body
    assert "docs/drafts/<story_name>/<story_name>-spec.md" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_skill_content.py -v`
Expected: FAIL — `assert "## Autonomous Mode" in body` fails

- [ ] **Step 3: Add the section**

In `psalm_saga/skills/story-brainstorming/SKILL.md`, find this exact text at the end of the file:

```markdown
## Handoff

End by stating explicitly: "Spec complete. [Invoking adapting-existing-work next. / Ready for writing-story-plans.]"
```

Replace it with (inserting the new section before `## Handoff`):

```markdown
## Autonomous Mode

Only active when `batch-story-generation` is the force-injected bootstrap
for this session (a `psalm-saga-batch` run). In every other session,
ignore this section — the hard gates above (ask, don't propose; get
explicit sign-off) are the only rule you follow.

**Save path override:** save the spec to
`docs/drafts/<story_name>/<story_name>-spec.md` instead of
`docs/psalm-saga/<slug>-spec.md` — `story_name` is this story's own
kebab-case slug (see `batch-story-generation`'s naming convention),
consistent across its spec, plan, and chapter files.

**Decide, don't ask.** Every dimension question in the Process above still
gets answered — concretely, not vaguely — but you answer it yourself.
Which input mode you're working from changes what you're answering *from*:

- **Scratch:** invent the premise and all six dimensions freely. Read
  `docs/drafts/_batch-log.md` first (see `batch-story-generation`) and
  reroll before locking anything that reads as a near-duplicate of an
  already-logged story.
- **Context:** the CLI gives you one or more inspiration texts (inline or
  from files). Read them for premise-grounding only — they don't fix any
  dimension by themselves; every dimension is still yours to decide,
  informed by that material.
- **Template:** the CLI gives you one or more template documents. Each one
  states some dimensions explicitly (or partially) and leaves the rest
  unstated. Keep every explicitly-templated answer exactly as given; for
  whatever's left unstated, decide it yourself, staying consistent with
  what the template already committed to.
- **Variant:** the CLI names one source file and the specific dimension(s)
  to change for it (from the run's variant manifest). Follow the
  Source-Derived Variance Check in the Process above exactly, with one
  change: skip "present the baseline to your human partner and get
  confirmation or edits" — draft the baseline faithfully from the source
  and lock it immediately. Only the manifest-named dimension(s) get
  freshly decided; walk those the normal way, just deciding instead of
  asking.

**Self-approve instead of getting sign-off.** Still run the
cross-dimension consistency pass (Step 5) in full. If you find a
contradiction, resolve it yourself and say so in the spec's own text (e.g.
"World-Building's material detail was narrowed from X to Y to stay
consistent with Character's Z") rather than stopping to ask which side to
revise. Once the spec is internally consistent, treat it as signed off and
move straight to `writing-story-plans` (its own Autonomous Mode section).

## Handoff

End by stating explicitly: "Spec complete. [Invoking adapting-existing-work next. / Ready for writing-story-plans.]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_content.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/story-brainstorming/SKILL.md tests/unit/test_skill_content.py
git commit -m "feat(skills): add Autonomous Mode to story-brainstorming for batch runs"
```

---

### Task 7: Autonomous Mode section in `writing-story-plans`

**Files:**
- Modify: `psalm_saga/skills/writing-story-plans/SKILL.md`
- Modify: `tests/unit/test_skill_content.py`

**Interfaces:**
- Produces: a `## Autonomous Mode` section in `writing-story-plans/SKILL.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_skill_content.py`:

```python
def test_writing_story_plans_has_autonomous_mode_section() -> None:
    body = _read_skill("writing-story-plans")

    assert "## Autonomous Mode" in body
    assert "docs/drafts/<story_name>/<story_name>-plan.md" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_skill_content.py::test_writing_story_plans_has_autonomous_mode_section -v`
Expected: FAIL — `assert "## Autonomous Mode" in body` fails

- [ ] **Step 3: Add the section**

In `psalm_saga/skills/writing-story-plans/SKILL.md`, find this exact text:

```markdown
## Continuity Budget

For long works, decide now how later chapters will get continuity context without re-reading every prior chapter in full: a running one-paragraph continuity summary updated after each chapter, maintained as part of the plan file, is usually enough. Note the approach in the plan so `drafting-chapters` knows what to hand each writer subagent.

## Red Flags
```

Replace it with (inserting the new section between them):

```markdown
## Continuity Budget

For long works, decide now how later chapters will get continuity context without re-reading every prior chapter in full: a running one-paragraph continuity summary updated after each chapter, maintained as part of the plan file, is usually enough. Note the approach in the plan so `drafting-chapters` knows what to hand each writer subagent.

## Autonomous Mode

Only active when `batch-story-generation` is the force-injected bootstrap
for this session (a `psalm-saga-batch` run); ignore this section in every
other session.

**Save path override:** save the plan to
`docs/drafts/<story_name>/<story_name>-plan.md` instead of
`docs/psalm-saga/<slug>-plan.md`, matching this story's spec location.

**Skip Step 4's sign-off.** Instead, self-check: re-verify the dimension
carry-through table against the spec, and every chapter brief's POV,
scenes, characters, and world-building elements against what the spec
actually committed to. If a carry-through row can't be filled without
inflating the spec (see this skill's own red flag on that), don't invent
the missing specificity yourself — go back to the signed-off spec text and
pick the narrowest reading that stays inside its literal wording, note
that reasoning inline in the plan, and proceed. Once every row and every
brief checks out, treat the plan as signed off and move straight to
`drafting-chapters` (unchanged for batch mode).

## Red Flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_content.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/writing-story-plans/SKILL.md tests/unit/test_skill_content.py
git commit -m "feat(skills): add Autonomous Mode to writing-story-plans for batch runs"
```

---

### Task 8: Autonomous Mode section in `reviewing-story-dimensions`

**Files:**
- Modify: `psalm_saga/skills/reviewing-story-dimensions/SKILL.md`
- Modify: `tests/unit/test_skill_content.py`

**Interfaces:**
- Produces: a `## Autonomous Mode` section in `reviewing-story-dimensions/SKILL.md`, including the fix-loop cap and abandonment rule `batch-story-generation` (Task 5) refers to.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_skill_content.py`:

```python
def test_reviewing_story_dimensions_has_autonomous_mode_section() -> None:
    body = _read_skill("reviewing-story-dimensions")

    assert "## Autonomous Mode" in body
    assert "ABANDONED.md" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_skill_content.py::test_reviewing_story_dimensions_has_autonomous_mode_section -v`
Expected: FAIL — `assert "## Autonomous Mode" in body` fails

- [ ] **Step 3: Add the section**

In `psalm_saga/skills/reviewing-story-dimensions/SKILL.md`, find this exact text:

```markdown
- **Source Relationship findings** (adaptations only): flag explicitly if the checklist shows the draft reading *more* evocative or similar to the source than the declared relationship intended — for example, the spec named "pastiche, homage tone" but the draft reads closer to mockery, or an intended "transformative retelling" reads as a near-scene-for-scene copy. This is exactly the kind of drift PSALM's own experiments found supervised fine-tuning induces even without any deliberate intent to copy — catching it here, at the checklist level, is the inexpensive check to run before anyone considers an actual PSALM comparison against the source.

## Red Flags
```

Replace it with (inserting the new section between them):

```markdown
- **Source Relationship findings** (adaptations only): flag explicitly if the checklist shows the draft reading *more* evocative or similar to the source than the declared relationship intended — for example, the spec named "pastiche, homage tone" but the draft reads closer to mockery, or an intended "transformative retelling" reads as a near-scene-for-scene copy. This is exactly the kind of drift PSALM's own experiments found supervised fine-tuning induces even without any deliberate intent to copy — catching it here, at the checklist level, is the inexpensive check to run before anyone considers an actual PSALM comparison against the source.

## Autonomous Mode

Only active when `batch-story-generation` is the force-injected bootstrap
for this session (a `psalm-saga-batch` run); ignore this section in every
other session.

**Save path:** write/update the findings table to
`docs/drafts/<story_name>/<story_name>-review.md` after every pass (each
per-chapter review and the final whole-story review), so the promoted
directory carries a record of the review that actually passed.

**Partial is never a judgement call here.** Treat every `Partial` finding
exactly like `Missing` — a gap that gets fixed, not a "probably fine, move
on." There's no one to ask, so don't leave ambiguity unresolved: decide
what "fully covered" requires and fix the draft to meet it.

**Fix-loop cap, per chapter:** attempt 1 is an in-context fix pass on the
existing draft; attempts 2 and 3 are fresh `chapter-writer` redispatches
that name the remaining gap explicitly (same escalation `drafting-chapters`
already uses for larger gaps). If the chapter still isn't fully `Covered`
after 3 total attempts, stop trying to fix it. Write
`docs/drafts/<story_name>/ABANDONED.md` stating which chapter and
dimension never converged and why, do not promote this story to
`docs/stories/`, and end your turn — `batch-story-generation`'s CLI loop
will generate a fresh replacement story to still reach the requested
count. This should be rare; it exists only as a bound so a single story
can never hang the whole batch.

**Source Relationship findings (variant mode):** if the checklist shows
the draft reading more evocative or similar to the source than the
declared relationship intended, don't just flag it — fix it the same way
as any other gap (a redispatch with the drift named explicitly), then
re-check.

## Red Flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_content.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/skills/reviewing-story-dimensions/SKILL.md tests/unit/test_skill_content.py
git commit -m "feat(skills): add Autonomous Mode and fix-loop cap to reviewing-story-dimensions"
```

---

### Task 9: Share `extract_tool_call_lines` via `stream_renderer.py`

**Files:**
- Modify: `psalm_saga/stream_renderer.py`
- Modify: `psalm_saga/cli.py`
- Create: `tests/unit/test_stream_renderer.py`

**Interfaces:**
- Produces: `extract_tool_call_lines(update: dict[str, Any]) -> list[str]` in `psalm_saga.stream_renderer`, replacing the private `_extract_tool_call_lines` that used to live only in `cli.py`. Consumed by `cli.py` (updated here) and `batch_cli.py` (Task 11).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_stream_renderer.py`:

```python
"""Tests for `psalm_saga.stream_renderer.extract_tool_call_lines`.

Moved here (from a private helper in `cli.py`) so both `psalm-saga` and
`psalm-saga-batch` can render tool-dispatch status lines from the same
best-effort LangGraph `updates`-mode payload shape.
"""

from __future__ import annotations

from typing import Any

from psalm_saga.stream_renderer import extract_tool_call_lines


class _FakeToolCallMessage:
    def __init__(self, tool_calls: list[dict[str, Any]]) -> None:
        self.tool_calls = tool_calls


def test_extract_tool_call_lines_names_a_plain_tool_call() -> None:
    update = {"model": {"messages": [_FakeToolCallMessage([{"name": "write_file"}])]}}

    assert extract_tool_call_lines(update) == ["write_file"]


def test_extract_tool_call_lines_names_the_dispatched_subagent() -> None:
    update = {
        "model": {
            "messages": [
                _FakeToolCallMessage(
                    [{"name": "task", "args": {"subagent_type": "chapter-writer"}}]
                )
            ]
        }
    }

    assert extract_tool_call_lines(update) == ["dispatching chapter-writer"]


def test_extract_tool_call_lines_returns_empty_for_no_model_key() -> None:
    assert extract_tool_call_lines({}) == []


def test_extract_tool_call_lines_returns_empty_on_malformed_payload() -> None:
    assert extract_tool_call_lines({"model": "not-a-dict-with-messages"}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_stream_renderer.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_tool_call_lines'`

- [ ] **Step 3: Move the function**

In `psalm_saga/stream_renderer.py`, add this function right after `extract_text` (before the `StreamRenderer` class):

```python
def extract_tool_call_lines(update: dict[str, Any]) -> list[str]:
    """Best-effort extraction of tool-call announcements from a LangGraph
    `updates`-mode payload for the main agent's `model` node.

    This is a convenience for terminal feedback, not load-bearing — if the
    update shape doesn't match what's expected (e.g. a deepagents internal
    change), it returns nothing rather than raising.
    """
    lines: list[str] = []
    try:
        model_output = update.get("model")
        if not model_output:
            return lines
        for message in model_output.get("messages", []):
            for tool_call in getattr(message, "tool_calls", None) or []:
                name = tool_call.get("name", "tool")
                if name == "task":
                    subagent = tool_call.get("args", {}).get("subagent_type", "?")
                    lines.append(f"dispatching {subagent}")
                else:
                    lines.append(name)
    except Exception:  # noqa: BLE001 — status lines are best-effort only
        return lines
    return lines
```

In `psalm_saga/cli.py`:

1. Change the import line:

```python
from psalm_saga.stream_renderer import StreamRenderer, extract_text
```

to:

```python
from psalm_saga.stream_renderer import StreamRenderer, extract_text, extract_tool_call_lines
```

2. Delete the entire `_extract_tool_call_lines` function definition (the one starting `def _extract_tool_call_lines(update: dict[str, Any]) -> list[str]:` and its docstring/body).

3. Change its call site inside `run_session`:

```python
                elif mode == "updates":
                    for line in _extract_tool_call_lines(payload):
                        renderer.announce_tool_call(line)
```

to:

```python
                elif mode == "updates":
                    for line in extract_tool_call_lines(payload):
                        renderer.announce_tool_call(line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_stream_renderer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full unit suite to confirm no regressions**

Run: `uv run pytest tests/unit -v`
Expected: PASS (all tests, including the CLI still importing/working)

- [ ] **Step 6: Commit**

```bash
git add psalm_saga/stream_renderer.py psalm_saga/cli.py tests/unit/test_stream_renderer.py
git commit -m "refactor(cli): share tool-call-line extraction with batch_cli"
```

---

### Task 10: `batch_cli.py` — argument parsing & per-story instruction building

**Files:**
- Create: `psalm_saga/batch_cli.py`
- Test: `tests/unit/test_batch_cli.py`

**Interfaces:**
- Consumes: `BatchInputError`, `resolve_context_inputs`, `resolve_template_inputs`, `resolve_variant_sources`, `VariantSource` from `psalm_saga.batch_inputs` (Task 1).
- Produces (this task): `_parse_args(argv: list[str] | None = None) -> argparse.Namespace`; `_resolve_inputs(args: argparse.Namespace) -> list[str] | list[VariantSource] | None`; `_build_story_instruction(story_index: int, count: int, mode: str, combine: str, inputs: Any, existing_names: set[str]) -> str`. Consumed by `run_batch`/`main` (Task 11, same module).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_batch_cli.py`:

```python
"""Tests for `psalm_saga.batch_cli`'s argument parsing/validation and
per-story instruction building — the pieces that don't need a running
agent. See the main-loop tests further down this file for `run_batch`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from psalm_saga.batch_cli import _build_story_instruction, _parse_args


def test_parse_args_defaults_combine_to_mixed_for_context() -> None:
    args = _parse_args(["--count", "3", "--mode", "context", "--context", "a spooky forest"])

    assert args.combine == "mixed"


def test_parse_args_forces_combine_separate_for_variant() -> None:
    args = _parse_args(
        ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "separate"]
    )

    assert args.combine == "separate"


def test_parse_args_rejects_combine_mixed_for_variant() -> None:
    with pytest.raises(SystemExit):
        _parse_args(
            ["--count", "2", "--mode", "variant", "--source-path", "sources", "--combine", "mixed"]
        )


def test_parse_args_rejects_count_below_one() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--count", "0", "--mode", "scratch"])


def test_parse_args_collects_repeated_context_paths() -> None:
    args = _parse_args(
        [
            "--count",
            "1",
            "--mode",
            "context",
            "--context-path",
            "a.txt",
            "--context-path",
            "b.txt",
        ]
    )

    assert args.context_paths == [Path("a.txt"), Path("b.txt")]


def test_build_story_instruction_for_scratch_mode() -> None:
    message = _build_story_instruction(1, 5, "scratch", "mixed", None, set())

    assert "story 1 of 5" in message
    assert "Mode: scratch" in message


def test_build_story_instruction_includes_existing_names() -> None:
    message = _build_story_instruction(2, 5, "context", "mixed", ["a spooky forest"], {"story-a"})

    assert "story-a" in message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_batch_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'psalm_saga.batch_cli'`

- [ ] **Step 3: Write the implementation (parsing/resolution pieces only)**

Create `psalm_saga/batch_cli.py`:

```python
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
from typing import Any

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
from psalm_saga.batch_session import existing_story_names, promoted_story_count
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


def _build_story_instruction(
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
```

(`run_batch` and `main` are added in Task 11 — this task's tests only exercise the three functions above.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_batch_cli.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add psalm_saga/batch_cli.py tests/unit/test_batch_cli.py
git commit -m "feat(batch): add batch_cli argument parsing and instruction building"
```

---

### Task 11: `batch_cli.py` — main loop (`run_batch`, `main`)

**Files:**
- Modify: `psalm_saga/batch_cli.py`
- Modify: `tests/unit/test_batch_cli.py`

**Interfaces:**
- Consumes: `build_agent`, `open_sqlite_checkpointer` from `psalm_saga.agent`; `existing_story_names`, `promoted_story_count` from `psalm_saga.batch_session` (Task 2); `BATCH_BOOTSTRAP_SKILL` from `psalm_saga.bootstrap` (Task 3); `extract_tool_call_lines`, `StreamRenderer` from `psalm_saga.stream_renderer` (Task 9); `_parse_args`, `_resolve_inputs`, `_build_story_instruction` (Task 10, same module).
- Produces: `run_batch(settings: Settings, args: argparse.Namespace, console: Console) -> None`; `main(argv: list[str] | None = None) -> None` (the `psalm-saga-batch` console-script entry point, registered in Task 12).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_batch_cli.py`:

```python
from contextlib import contextmanager
from typing import Iterator

from rich.console import Console

from psalm_saga import batch_cli
from psalm_saga.batch_session import promoted_story_count, stories_dir
from psalm_saga.settings import Settings


class _FakeAgent:
    def __init__(self, on_stream: Any) -> None:
        self._on_stream = on_stream

    def stream(self, *_args: Any, **_kwargs: Any) -> Iterator[Any]:
        self._on_stream()
        return iter(())


@contextmanager
def _fake_checkpointer(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    yield None


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.backend.root_dir = tmp_path
    return settings


def _quiet_console() -> Console:
    import io

    return Console(file=io.StringIO())


def test_run_batch_stops_once_count_is_reached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    calls: list[int] = []

    def on_stream() -> None:
        n = len(calls) + 1
        calls.append(n)
        (stories_dir(settings, session_id) / f"story-{n}").mkdir(parents=True)

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _FakeAgent(on_stream))

    args = batch_cli._parse_args(["--count", "3", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 3
    assert promoted_story_count(settings, session_id) == 3


def test_run_batch_gives_up_after_the_attempt_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    calls: list[int] = []

    def on_stream() -> None:
        calls.append(len(calls) + 1)
        # never promotes anything — simulates a systemically broken run

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _FakeAgent(on_stream))

    args = batch_cli._parse_args(["--count", "2", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 2 * batch_cli.MAX_ATTEMPT_MULTIPLIER
    assert promoted_story_count(settings, session_id) == 0


def test_run_batch_resumes_and_only_tops_up_the_remainder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    session_id = "session-1"
    (stories_dir(settings, session_id) / "already-done").mkdir(parents=True)
    calls: list[int] = []

    def on_stream() -> None:
        n = len(calls) + 1
        calls.append(n)
        (stories_dir(settings, session_id) / f"story-{n}").mkdir(parents=True)

    monkeypatch.setattr(batch_cli, "open_sqlite_checkpointer", _fake_checkpointer)
    monkeypatch.setattr(batch_cli, "build_agent", lambda *_a, **_kw: _FakeAgent(on_stream))

    args = batch_cli._parse_args(["--count", "3", "--mode", "scratch", "--session", session_id])
    batch_cli.run_batch(settings, args, _quiet_console())

    assert len(calls) == 2  # only the missing 2, not 3
    assert promoted_story_count(settings, session_id) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_batch_cli.py -v -k run_batch`
Expected: FAIL with `AttributeError: module 'psalm_saga.batch_cli' has no attribute 'run_batch'`

- [ ] **Step 3: Implement `run_batch` and `main`**

Append to `psalm_saga/batch_cli.py` (after `_build_story_instruction`):

```python
def run_batch(settings: Settings, args: argparse.Namespace, console: Console) -> None:
    """Generate stories until `docs/stories/` for this session holds
    `args.count` of them (or the overall attempt cap is hit).

    Never trusts the agent's own claim of success — after every per-story
    turn, `promoted_story_count` re-scans the filesystem, which is the only
    thing that decides whether the loop continues.
    """
    session_id = args.session_id or generate_session_id()
    console.print(f"[dim]Session:[/dim] {session_id}")
    console.print(f"[dim]Session directory:[/dim] {session_directory(settings, session_id)}\n")

    inputs = _resolve_inputs(args)

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
            message = _build_story_instruction(
                done + 1, args.count, args.mode, args.combine, inputs, names
            )
            console.print(f"[bold magenta]batch>[/bold magenta] attempt {attempts}: {message}\n")

            renderer = StreamRenderer(console)
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
            renderer.finish()
            console.print()

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

    try:
        args = _parse_args(argv)
    except SystemExit:
        raise

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_batch_cli.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the full unit suite to confirm no regressions**

Run: `uv run pytest tests/unit -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add psalm_saga/batch_cli.py tests/unit/test_batch_cli.py
git commit -m "feat(batch): add psalm-saga-batch main loop with resume and attempt cap"
```

---

### Task 12: Register the `psalm-saga-batch` console script

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: the `psalm-saga-batch` console-script entry point, resolving to `psalm_saga.batch_cli:main` (Task 11).

- [ ] **Step 1: Edit `pyproject.toml`**

Change:

```toml
[project.scripts]
psalm-saga = "psalm_saga.cli:main"
```

to:

```toml
[project.scripts]
psalm-saga = "psalm_saga.cli:main"
psalm-saga-batch = "psalm_saga.batch_cli:main"
```

- [ ] **Step 2: Reinstall in editable mode so the new script is registered**

Run: `uv sync --group dev`
Expected: completes without error; `psalm-saga-batch` now resolvable on `PATH` inside the project's venv.

- [ ] **Step 3: Smoke-test the entry point**

Run: `uv run psalm-saga-batch --help`
Expected: argparse help text listing `--count`, `--mode`, `--context`, `--context-path`, `--template-path`, `--source-path`, `--variant-manifest`, `--combine`, `--session`, `--model`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(packaging): register psalm-saga-batch console script"
```

---

### Task 13: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Add a Features bullet**

In `README.md`, find this line inside the `## Features` list:

```markdown
- **Usable outside the CLI.** The skills are plain `SKILL.md` files
  following the Agent Skills spec, so they work in Claude Code or any other
  harness that reads that format.
```

Add immediately after it:

```markdown
- **Batch generation.** `psalm-saga-batch` generates many complete stories
  in one session with no human interaction — from scratch, from your own
  inspiration material, from partial templates, or as dimension-varied
  takes on an existing source. See "Batch generation" below.
```

- [ ] **Step 2: Add a "Batch generation" section**

Find the end of the `## Sessions` section — the text ending with:

```markdown
Sessions never share a directory, so multiple stories in the same project
never collide. Session ids are UUIDv7: their leading bits encode a
millisecond timestamp, so the id itself sorts in creation order. No
separate timestamp is needed in the directory name, and `ls sessions/`
lists sessions oldest to newest.

## The workflow
```

Insert a new section between them:

```markdown
Sessions never share a directory, so multiple stories in the same project
never collide. Session ids are UUIDv7: their leading bits encode a
millisecond timestamp, so the id itself sorts in creation order. No
separate timestamp is needed in the directory name, and `ls sessions/`
lists sessions oldest to newest.

## Batch generation

`psalm-saga-batch` generates many complete stories in one session with no
human interaction at all — every dimension, sign-off, and review judgement
call that an interactive session asks you for, a batch session decides for
itself.

```bash
psalm-saga-batch --count 10 --mode scratch
psalm-saga-batch --count 5 --mode context --context "a lighthouse keeper who finds a message from someone unborn"
psalm-saga-batch --count 4 --mode template --template-path ./templates
psalm-saga-batch --count 6 --mode variant --source-path ./drafts --variant-manifest ./drafts/variant-manifest.json
```

| Mode       | Inputs                                                       | What the system does                                                                                |
|------------|----------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `scratch`  | none                                                            | Invents premise and all six dimensions freely.                                                       |
| `context`  | `--context TEXT` and/or `--context-path PATH` (file or dir)     | Uses the given text/files as inspiration only; every dimension is still freely decided.              |
| `template` | `--template-path PATH` (file or dir)                            | Treats each file as partial dimension answers and creatively completes the rest.                     |
| `variant`  | `--source-path PATH` + `--variant-manifest FILE`                | Locks every dimension from the source except the manifest-named one(s), which are freshly decided.   |

`--combine {mixed,separate}` controls how multiple inputs map onto
`--count` stories: `mixed` (default for `context`/`template`) lets any
story draw on more than one input; `separate` (the only option for
`variant`) keeps each story anchored to exactly one input. A
`variant-manifest.json` maps each source file to the dimension(s) to vary
for it:

```json
[
  {"source": "old-draft.md", "dimensions": ["character", "world-building"]}
]
```

If `--variant-manifest` is omitted, `psalm-saga-batch` looks for
`variant-manifest.json` inside a given `--source-path` directory.

A batch session lays out `docs/` differently from an interactive one:
`docs/drafts/<story_name>/` holds a story's spec, plan, chapters, and
review report while its pipeline runs; `docs/stories/<story_name>/` holds
the same files once that story's review is fully clean. `--count` is the
target *total* stories in `docs/stories/` — re-running
`psalm-saga-batch --session <id> --count 10` against a session that
already has some tops up only the remainder.

See `docs/superpowers/specs/2026-08-24-batch-story-generation-design.md`
for the full design.

## The workflow
```

- [ ] **Step 3: Remove the now-implemented roadmap bullet**

Find this bullet at the start of the `## Roadmap` section:

```markdown
## Roadmap

- **Non-interactive mode for batch generation.** A scriptable entry point
  that runs a full brainstorm-to-draft pipeline from a pre-filled spec
  instead of an interactive session, for generating many stories under
  controlled conditions without manual involvement in each one.
- **Experiments and evaluation infrastructure.**
```

Replace it with (removing the now-shipped bullet):

```markdown
## Roadmap

- **Experiments and evaluation infrastructure.**
```

(leave the rest of that bullet's own text — "Tooling for running generation at scale..." — exactly as it already reads, only the batch-generation bullet above it is removed.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document psalm-saga-batch and mark it off the roadmap"
```

---

## Self-Review

**Spec coverage:**
- CLI surface (`--count`, `--mode`, per-mode inputs, `--combine`, `--session`, `--model`) → Tasks 10-11.
- Directory layout (`docs/drafts/`, `docs/stories/`) → Task 2, referenced by Tasks 6-8 and 11.
- Four input modes (scratch/context/template/variant) → Task 1 (resolution) + Tasks 6 (autonomous dimension decisions per mode).
- `--combine mixed/separate`, forced `separate` for variant → Task 10.
- Per-story pipeline (autonomous brainstorming → planning → drafting (unchanged) → review-and-fix → promote) → Tasks 5-8.
- Fix-loop safety bound (3 attempts, abandon story) → Task 8.
- Resume handling (count existing, top up remainder, treat interrupted drafts as abandoned) → Task 11 (promotion counting drives the loop) + Task 8 (abandonment is a skill-level instruction, not code — the CLI never needs to distinguish "abandoned" from "not yet attempted," it just rescans `docs/stories/`).
- Overall attempt cap (`count * 3`) → Task 11 (`MAX_ATTEMPT_MULTIPLIER`).
- Error handling (uncaught exception doesn't crash the whole batch) — **gap found and left as a documented follow-up**: the current `run_batch` loop does not wrap the `agent.stream()` call in a per-attempt try/except, so an uncaught exception from one story's turn would currently propagate and end the whole batch rather than being logged and retried. This is a deliberate scope cut for this plan — the spec's stated behavior (log, leave the draft, continue) needs a decision about which exceptions are safe to swallow (a `KeyboardInterrupt` should still stop the run, for instance) that's better made once the happy path is running end-to-end and real failure modes are observed. Tracked as a fast-follow, not silently dropped.
- Testing plan (unit tests for mechanical pieces, evals for behavioral content) → Tasks 1-2, 9-11 (unit) and the note in the spec that eval coverage is a separate, later addition to `tests/evals/`.

**Placeholder scan:** no TBD/TODO markers; the one gap above is called out explicitly with a reason, not left as a vague "handle errors" step.

**Type consistency:** `VariantSource(source_path: Path, dimensions: tuple[str, ...])` (Task 1) is used identically in `batch_inputs.py`, `batch_cli.py`'s `_resolve_inputs`/`_build_story_instruction` (Task 10), and the type hints there (`list[str] | list[VariantSource] | None`). `promoted_story_count`/`existing_story_names`/`story_draft_dir`/`story_final_dir` (Task 2) are called with the same `(settings, session_id, ...)` argument order everywhere they're used (Tasks 5-8's prose, Task 11's code). `BATCH_BOOTSTRAP_SKILL` (Task 3) is the same string used in Task 5's `SKILL.md` frontmatter `name:` field and Task 11's `build_agent(..., bootstrap_skill=BATCH_BOOTSTRAP_SKILL)` call. `extract_tool_call_lines` (Task 9) has the same signature (`dict[str, Any] -> list[str]`) in its new home and at both call sites (`cli.py`, `batch_cli.py`).
