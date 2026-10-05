"""C1 (Full pipeline) backend: spec -> plan -> draft -> review -> repair,
via `psalm_saga`'s own `build_agent()`, one session per story attempt.

Follows the same invocation shape `psalm_saga.batch_cli.run_batch` already
uses for `psalm-saga-batch`, but one job = one story (not one session
generating many stories) — see spec §5. A job makes up to
`MAX_STORY_ATTEMPTS` fresh-session attempts; an attempt the review loop
abandons is retried from scratch.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from experiments.pipeline.generators import resolve_model
from experiments.pipeline.length import directive_for
from experiments.pipeline.models import GenerationJob, GenerationResult, JobAbandoned, JobFailed
from experiments.pipeline.progress import (
    WRITE_TOOLS,
    ProgressSink,
    stage_for_tool_call,
    tool_calls_from_update,
)
from experiments.pipeline.resolver import ResolvedInput
from psalm_saga.agent import build_agent, open_sqlite_checkpointer
from psalm_saga.batch_session import drafts_dir, promote_story
from psalm_saga.bootstrap import BATCH_BOOTSTRAP_SKILL
from psalm_saga.session import generate_session_id, session_directory
from psalm_saga.settings import Settings

_TASK_INSTRUCTIONS: dict[str, str] = {
    "A": "Generate a complete story from this premise, using the batch-story-generation skill:\n\n{content}",
    "B": (
        "Generate a complete story that instantiates this specification exactly. "
        "The specification below is already final — do not re-elicit it, only carry "
        "it into a plan and drafted chapters. Use the batch-story-generation skill:\n\n{content}"
    ),
    "C": (
        "Extract a dimension specification from this source story, then produce six "
        "variants — one per dimension — each regenerating exactly one dimension and "
        "locking the other five. Use the batch-story-generation skill:\n\n{content}"
    ),
    "D": (
        "Produce six variants of a story from this already-authored specification — "
        "one per dimension, each regenerating exactly one dimension and locking the "
        "other five. No extraction step is needed; the specification below is already "
        "final. Use the batch-story-generation skill:\n\n{content}"
    ),
}

MAX_STORY_ATTEMPTS = 3
"""Story attempts per job. Matches the per-chapter fix-loop cap in `reviewing-story-dimensions`."""


@dataclass
class _AttemptOutcome:
    """What one fresh-session story attempt left behind."""

    session_id: str
    promoted: list[str]
    abandoned_reason: str
    artifacts: dict[str, str]


class _FixLoopDetector:
    """Spots review writes that re-check a rewritten chapter.

    `reviewing-story-dimensions` rewrites one `<story>-review.md` after every
    pass, so a second review write alone is not a fix: it is usually the next
    chapter's first review. A review starts a fix cycle when a chapter written
    since that story's previous review had already been written before it.

    One session can draft several stories (tasks B-D produce variants), each in
    its own draft directory, so chapters are tracked per draft directory: a
    review only counts chapters that live beside its own review file.
    """

    def __init__(self) -> None:
        self._reviewed: defaultdict[str, set[int]] = defaultdict(set)
        self._since_review: defaultdict[str, set[int]] = defaultdict(set)
        self.cycles = 0

    def observe(self, name: str, args: dict[str, Any]) -> tuple[str, int] | None:
        """Feed one tool call; return `(review file, chapter)` when it starts a fix cycle."""
        path = str(args.get("file_path", ""))
        draft_dir = str(PurePosixPath(path.replace("\\", "/")).parent)
        stage = stage_for_tool_call(name, args)
        if stage is not None and stage.startswith("chapter "):
            self._since_review[draft_dir].add(int(stage.removeprefix("chapter ")))
            return None
        if name not in WRITE_TOOLS or not path.endswith("-review.md"):
            return None
        since_review = self._since_review.pop(draft_dir, set())
        rewritten = since_review & self._reviewed[draft_dir]
        self._reviewed[draft_dir] |= since_review
        if not rewritten:
            return None
        self.cycles += 1
        return path, min(rewritten)


class FullPipelineBackend:
    """Runs one job through the full `psalm_saga` agent pipeline (C1)."""

    def run(
        self, job: GenerationJob, input_ref: ResolvedInput, progress: ProgressSink
    ) -> GenerationResult:
        settings = Settings()
        model_id = resolve_model(job.generator_family)
        settings.agent.orchestration_model_name = model_id
        settings.agent.subagent_model_name = model_id

        instruction_template = _TASK_INSTRUCTIONS[job.task]
        instruction = instruction_template.format(content=input_ref.content)
        if job.length_range is not None:
            instruction = f"{directive_for(job.length_range)}\n\n{instruction}"

        timeline: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        all_artifacts: dict[str, str] = {}
        last_reason = ""
        winner: tuple[int, _AttemptOutcome] | None = None

        try:
            for attempt in range(1, MAX_STORY_ATTEMPTS + 1):
                progress.stage(f"attempt {attempt}/{MAX_STORY_ATTEMPTS}")
                outcome = self._run_attempt(
                    settings,
                    job,
                    instruction,
                    attempt=attempt,
                    progress=progress,
                    timeline=timeline,
                    trace=trace,
                )
                all_artifacts.update(_under_attempt(attempt, outcome.artifacts))
                if outcome.promoted:
                    winner = (attempt, outcome)
                    timeline.append(_event("attempt_done", attempt, promoted=outcome.promoted))
                    break
                last_reason = outcome.abandoned_reason
                timeline.append(_event("attempt_abandoned", attempt, reason=last_reason))
        except Exception as exc:
            # Keep the failing attempt's partial docs beside the earlier attempts' evidence.
            started = [e for e in timeline if e["event"] == "attempt_started"]
            if started:
                with contextlib.suppress(OSError, ValueError):
                    docs = self._collect_artifacts(settings, started[-1]["session_id"])
                    all_artifacts.update(_under_attempt(started[-1]["attempt"], docs))
            all_artifacts["attempts.jsonl"] = _timeline_jsonl(timeline)
            config = _config(settings, job, instruction_template, timeline)
            # str(exc) is blank for many bare exceptions; fall back to repr so the error column is never empty.
            raise JobFailed(
                str(exc) or repr(exc), artifacts=all_artifacts, trace=trace, config=config
            ) from exc

        all_artifacts["attempts.jsonl"] = _timeline_jsonl(timeline)
        config = _config(settings, job, instruction_template, timeline)
        if winner is None:
            raise JobAbandoned(last_reason, artifacts=all_artifacts, trace=trace, config=config)

        attempt_no, outcome = winner
        winning_docs = outcome.artifacts
        artifacts = {**winning_docs, **all_artifacts}
        config.update(
            {
                "psalm_saga_session_id": outcome.session_id,
                "promoted_stories": outcome.promoted,
                "winning_attempt": attempt_no,
                "realised_words": _realised_words(winning_docs, outcome.promoted),
            }
        )
        return GenerationResult(artifacts=artifacts, trace=trace, config=config)

    def _run_attempt(  # noqa: PLR0913
        self,
        settings: Settings,
        job: GenerationJob,
        instruction: str,
        *,
        attempt: int,
        progress: ProgressSink,
        timeline: list[dict[str, Any]],
        trace: list[dict[str, Any]],
    ) -> _AttemptOutcome:
        """Run one story attempt in a fresh session; return what it promoted or why it stopped.

        Appends `attempt_started` and any `fix_loop_activated` events to
        `timeline`, and this attempt's messages (tagged with `attempt`) to
        `trace` as they arrive, so both survive an exception. The caller
        records `attempt_done` / `attempt_abandoned`.
        """
        session_id = generate_session_id()
        timeline.append(_event("attempt_started", attempt, session_id=session_id))
        trace.append({"type": "HumanMessage", "content": instruction, "attempt": attempt})
        fix_loop = _FixLoopDetector()

        with open_sqlite_checkpointer(settings, session_id) as checkpointer:
            agent = build_agent(
                settings,
                session_id=session_id,
                checkpointer=checkpointer,
                bootstrap_skill=BATCH_BOOTSTRAP_SKILL,
            )
            for kind, item in self._stream_run(agent, session_id, instruction, progress):
                if kind == "trace":
                    trace.append({**item, "attempt": attempt})
                    continue
                name, args = item
                fix = fix_loop.observe(name, args)
                if fix is not None:
                    review_file, chapter = fix
                    timeline.append(
                        _event(
                            "fix_loop_activated",
                            attempt,
                            chapter=chapter,
                            cycle=fix_loop.cycles,
                            review_file=review_file,
                        )
                    )
                    progress.stage(f"fix attempt {fix_loop.cycles}")

        promoted = self._promote_finished_drafts(settings, session_id)
        abandoned_reason = ""
        if not promoted:
            abandoned_reason = _abandoned_reason(settings, session_id)
            if not abandoned_reason:
                raise RuntimeError(
                    f"No story was completed for job {job.job_id} (attempt {attempt}): no draft "
                    "under this session carries a DONE.md marker and none was abandoned. The "
                    "pipeline stage may have hit a model-call or tool-call limit, or the agent "
                    "may not have finished."
                )

        return _AttemptOutcome(
            session_id=session_id,
            promoted=promoted,
            abandoned_reason=abandoned_reason,
            artifacts=self._collect_artifacts(settings, session_id),
        )

    def _stream_run(
        self, agent: Any, session_id: str, instruction: str, progress: ProgressSink
    ) -> Iterator[tuple[str, Any]]:
        """Run the agent, reporting stage changes and yielding tagged stream items.

        Yields `("trace", entry)` for every message and `("tool", (name, args))`
        for every tool call. `subgraphs=True` is required: deepagents runs
        subagents (e.g. `chapter-writer`) inside the `task` tool call, and their
        updates are hidden from the default stream. Each streamed item is then
        `(namespace, mode, payload)`; the top-level graph's namespace is `()`.
        """
        for namespace, mode, payload in agent.stream(
            {"messages": [{"role": "user", "content": instruction}]},
            config={"configurable": {"thread_id": session_id}},
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            if mode != "updates":
                continue
            namespace_label = "/".join(namespace)
            for node_update in payload.values() if isinstance(payload, dict) else []:
                if not isinstance(node_update, dict):
                    continue
                for message in node_update.get("messages", []) or []:
                    yield (
                        "trace",
                        {
                            "type": message.__class__.__name__,
                            "content": getattr(message, "content", ""),
                            "namespace": namespace_label,
                        },
                    )
            for name, args in tool_calls_from_update(payload):
                stage = stage_for_tool_call(name, args)
                if stage is not None:
                    progress.stage(stage)
                yield ("tool", (name, args))

    def _promote_finished_drafts(self, settings: Settings, session_id: str) -> list[str]:
        """Promote every draft directory carrying a `DONE.md` marker; return the promoted names.

        Mirrors `psalm_saga.batch_cli._promote_finished_drafts`: a draft lacking
        `DONE.md` (an abandoned or still-in-progress run) is left alone, never
        promoted, and never silently counted as a finished story.
        """
        drafts = drafts_dir(settings, session_id)
        if not drafts.is_dir():
            return []
        promoted: list[str] = []
        for draft in sorted(p for p in drafts.iterdir() if p.is_dir()):
            if not (draft / "DONE.md").is_file():
                continue
            promote_story(settings, session_id, draft.name)
            promoted.append(draft.name)
        return promoted

    def _collect_artifacts(self, settings: Settings, session_id: str) -> dict[str, str]:
        """Read every file this session's `docs/` tree produced, keyed by relative path."""
        docs_dir = session_directory(settings, session_id) / "docs"
        if not docs_dir.is_dir():
            return {}
        return {
            str(path.relative_to(docs_dir)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in sorted(docs_dir.rglob("*"))
            if path.is_file()
        }


def _abandoned_reason(settings: Settings, session_id: str) -> str:
    """Stripped text of the first draft's `ABANDONED.md`, or "" when no draft was abandoned.

    An empty marker file still counts as an abandonment; its reason then names the draft.
    """
    drafts = drafts_dir(settings, session_id)
    if not drafts.is_dir():
        return ""
    for marker in sorted(drafts.glob("*/ABANDONED.md")):
        if marker.is_file():
            return marker.read_text(encoding="utf-8").strip() or f"{marker.parent.name} abandoned"
    return ""


def _under_attempt(attempt: int, artifacts: dict[str, str]) -> dict[str, str]:
    """Re-key one attempt's docs under `attempts/<n>/`."""
    return {f"attempts/{attempt}/{path}": text for path, text in artifacts.items()}


def _timeline_jsonl(timeline: list[dict[str, Any]]) -> str:
    """The `attempts.jsonl` text: one JSON object per timeline event."""
    return "".join(json.dumps(event) + "\n" for event in timeline)


def _config(
    settings: Settings,
    job: GenerationJob,
    instruction_template: str,
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reproducibility snapshot shared by every outcome (done, abandoned, failed)."""
    return {
        "orchestration_model_name": settings.agent.orchestration_model_name,
        "subagent_model_name": settings.agent.subagent_model_name,
        "model_kwargs": settings.agent.model_kwargs,
        "subagent_model_kwargs": settings.agent.subagent_model_kwargs,
        "task": job.task,
        "condition": job.condition,
        "length_range": job.length_range,
        "attempts": len([e for e in timeline if e["event"] == "attempt_started"]),
        "prompt_template_sha256": hashlib.sha256(instruction_template.encode("utf-8")).hexdigest(),
    }


def _event(name: str, attempt: int, **fields: Any) -> dict[str, Any]:
    """One `attempts.jsonl` line: event name, attempt number, UTC timestamp, extra fields."""
    return {
        "event": name,
        "attempt": attempt,
        "at": datetime.now(UTC).isoformat(),
        **fields,
    }


def _realised_words(artifacts: dict[str, str], promoted: list[str]) -> int | None:
    """Word count of the first promoted story, or None when nothing was promoted."""
    if not promoted:
        return None
    text = artifacts.get(f"stories/{promoted[0]}.md")
    return len(text.split()) if text is not None else None


BACKEND = FullPipelineBackend()
