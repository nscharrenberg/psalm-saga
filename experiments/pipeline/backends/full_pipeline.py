"""C1 (Full pipeline) backend: spec -> plan -> draft -> review -> repair,
via `psalm_saga`'s own `build_agent()`, one session per job.

Follows the same invocation shape `psalm_saga.batch_cli.run_batch` already
uses for `psalm-saga-batch`, but one job = one independent session (not
one session generating many stories) — see spec §5.
"""

from __future__ import annotations

from psalm_saga.agent import build_agent, open_sqlite_checkpointer
from psalm_saga.bootstrap import BATCH_BOOTSTRAP_SKILL
from psalm_saga.session import generate_session_id, session_directory
from psalm_saga.settings import Settings

from experiments.pipeline.generators import resolve_model
from experiments.pipeline.models import GenerationJob, GenerationResult
from experiments.pipeline.resolver import ResolvedInput

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


class FullPipelineBackend:
    """Runs one job through the full `psalm_saga` agent pipeline (C1)."""

    def run(self, job: GenerationJob, input_ref: ResolvedInput) -> GenerationResult:
        settings = Settings()
        model_id = resolve_model(job.generator_family)
        settings.agent.orchestration_model_name = model_id
        settings.agent.subagent_model_name = model_id

        session_id = generate_session_id()
        instruction = _TASK_INSTRUCTIONS[job.task].format(content=input_ref.content)

        with open_sqlite_checkpointer(settings, session_id) as checkpointer:
            agent = build_agent(
                settings,
                session_id=session_id,
                checkpointer=checkpointer,
                bootstrap_skill=BATCH_BOOTSTRAP_SKILL,
            )
            result = agent.invoke(
                {"messages": [{"role": "user", "content": instruction}]},
                config={"configurable": {"thread_id": session_id}},
            )
            trace = [
                {"type": message.__class__.__name__, "content": getattr(message, "content", "")}
                for message in result["messages"]
            ]
            artifacts = self._collect_artifacts(settings, session_id)

        return GenerationResult(
            artifacts=artifacts,
            trace=trace,
            config={
                "orchestration_model_name": settings.agent.orchestration_model_name,
                "subagent_model_name": settings.agent.subagent_model_name,
                "psalm_saga_session_id": session_id,
                "task": job.task,
                "condition": job.condition,
            },
        )

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


BACKEND = FullPipelineBackend()
