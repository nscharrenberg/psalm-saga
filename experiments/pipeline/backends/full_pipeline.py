"""C1 (Full pipeline) backend: spec -> plan -> draft -> review -> repair,
via `psalm_saga`'s own `build_agent()`, one session per story attempt.

Follows the same invocation shape `psalm_saga.batch_cli.run_batch` already
uses for `psalm-saga-batch`, but one job = one story (not one session
generating many stories) — see spec §5. A job makes up to
`MAX_STORY_ATTEMPTS` fresh-session attempts; an attempt the review loop
abandons is retried from scratch.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from experiments.pipeline.generators import resolve_model
from experiments.pipeline.length import directive_for
from experiments.pipeline.models import GenerationJob, GenerationResult, JobAbandoned
from experiments.pipeline.progress import ProgressSink, stage_for_tool_call, tool_calls_from_update
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

_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


@dataclass
class _AttemptOutcome:
    """What one fresh-session story attempt left behind."""

    session_id: str
    promoted: list[str]
    abandoned_reason: str
    artifacts: dict[str, str]
    trace: list[dict[str, Any]]


class _FixLoopDetector:
    """Spots review writes that re-check a rewritten chapter.

    `reviewing-story-dimensions` rewrites one `<story>-review.md` after every
    pass, so a second review write alone is not a fix: it is usually the next
    chapter's first review. A review starts a fix cycle when a chapter written
    since the previous review had already been written before that review.
    """

    def __init__(self) -> None:
        self._reviewed: set[int] = set()
        self._since_review: set[int] = set()
        self.cycles = 0

    def observe(self, name: str, args: dict[str, Any]) -> str | None:
        """Feed one tool call; return the review file path when it starts a fix cycle."""
        stage = stage_for_tool_call(name, args)
        if stage is not None and stage.startswith("chapter "):
            self._since_review.add(int(stage.removeprefix("chapter ")))
            return None
        path = str(args.get("file_path", ""))
        if name not in _WRITE_TOOLS or not path.endswith("-review.md"):
            return None
        is_fix = bool(self._since_review & self._reviewed)
        self._reviewed |= self._since_review
        self._since_review = set()
        if not is_fix:
            return None
        self.cycles += 1
        return path


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
        winner: tuple[int, str, list[str]] | None = None

        for attempt in range(1, MAX_STORY_ATTEMPTS + 1):
            progress.stage(f"attempt {attempt}/{MAX_STORY_ATTEMPTS}")
            outcome = self._run_attempt(
                settings, job, instruction, attempt=attempt, progress=progress, timeline=timeline
            )
            trace.extend({**entry, "attempt": attempt} for entry in outcome.trace)
            all_artifacts.update(
                {f"attempts/{attempt}/{path}": text for path, text in outcome.artifacts.items()}
            )
            if outcome.promoted:
                winner = (attempt, outcome.session_id, outcome.promoted)
                timeline.append(_event("attempt_done", attempt, promoted=outcome.promoted))
                break
            last_reason = outcome.abandoned_reason
            timeline.append(_event("attempt_abandoned", attempt, reason=last_reason))

        all_artifacts["attempts.jsonl"] = "".join(json.dumps(e) + "\n" for e in timeline)
        config: dict[str, Any] = {
            "orchestration_model_name": settings.agent.orchestration_model_name,
            "subagent_model_name": settings.agent.subagent_model_name,
            "model_kwargs": settings.agent.model_kwargs,
            "subagent_model_kwargs": settings.agent.subagent_model_kwargs,
            "task": job.task,
            "condition": job.condition,
            "length_range": job.length_range,
            "attempts": len([e for e in timeline if e["event"] == "attempt_started"]),
            "prompt_template_sha256": hashlib.sha256(
                instruction_template.encode("utf-8")
            ).hexdigest(),
        }
        if winner is None:
            raise JobAbandoned(last_reason, artifacts=all_artifacts, trace=trace, config=config)

        attempt_no, session_id, promoted = winner
        winning_docs = self._collect_artifacts(settings, session_id)
        artifacts = {**winning_docs, **all_artifacts}
        config.update(
            {
                "psalm_saga_session_id": session_id,
                "promoted_stories": promoted,
                "winning_attempt": attempt_no,
                "realised_words": _realised_words(winning_docs, promoted),
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
    ) -> _AttemptOutcome:
        """Run one story attempt in a fresh session; return what it promoted or why it stopped.

        Appends `attempt_started` and any `fix_loop_activated` events to
        `timeline`. The caller records `attempt_done` / `attempt_abandoned`.
        """
        session_id = generate_session_id()
        timeline.append(_event("attempt_started", attempt, session_id=session_id))
        trace: list[dict[str, Any]] = [{"type": "HumanMessage", "content": instruction}]
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
                    trace.append(item)
                    continue
                name, args = item
                review_file = fix_loop.observe(name, args)
                if review_file is not None:
                    timeline.append(
                        _event(
                            "fix_loop_activated",
                            attempt,
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
            trace=trace,
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
