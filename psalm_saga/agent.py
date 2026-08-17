"""Build the psalm-saga deep agent.

    from psalm_saga.agent import build_agent
    from psalm_saga.settings import Settings

    agent = build_agent(Settings())
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Let's write a short story about a lighthouse keeper"}]},
        config={"configurable": {"thread_id": "1"}},
    )

Three things happen here, mirroring how any deepagents-based harness needs
to be assembled:

1. **Skills.** The vendored `skills/` directory is mounted at a fixed
   backend route (`SKILLS_MOUNT`) via `CompositeBackend`, independent of
   wherever `settings.backend.root_dir` points the agent's own project
   files — so the skills are reachable regardless of what directory
   `psalm-saga` was launched from. `FilesystemBackend`-family backends treat
   every path as virtual and rooted at their own `root_dir`
   (`virtual_mode=True` is the default), so an absolute on-disk path to the
   installed skills wouldn't otherwise resolve against a backend rooted at
   the project directory.
2. **Bootstrap.** `bootstrap.compose_system_prompt` force-injects the full
   `using-psalm-saga/SKILL.md` into `system_prompt`, guaranteeing the
   spec-first workflow rule is present every turn rather than merely
   discoverable in a skill list.
3. **Subagents, middleware, and settings.** `chapter-writer` and
   `dimension-reviewer` are registered as named subagents (with their own
   model override from settings); `TodoListMiddleware` is added since
   `write_todos` isn't included by `create_deep_agent` by default; the
   cross-cutting reliability middleware from `middleware.init_middleware`
   (retry, call limits, tool-error formatting) and an optional rate limiter
   are layered on top.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from deepagents.backends import (
    BackendProtocol,
    CompositeBackend,
    FilesystemBackend,
    LocalShellBackend,
)
from langchain.agents.middleware import TodoListMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.rate_limiters import InMemoryRateLimiter
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from psalm_saga.bootstrap import SKILLS_DIR, compose_system_prompt
from psalm_saga.middleware import init_middleware
from psalm_saga.settings import Settings

# Fixed so the skills are reachable regardless of `settings.backend.root_dir`
# — see the module docstring's point 1.
SKILLS_MOUNT = "/psalm-saga-skills/"

CHAPTER_WRITER_SUBAGENT: SubAgent = {
    "name": "chapter-writer",
    "description": (
        "Use to draft a single chapter's prose, per the drafting-chapters "
        "skill. Give it the dimension spec (or relevant excerpts), the "
        "story plan's dimension carry-through table, this chapter's brief "
        "in full, and the running continuity summary — not every prior "
        "chapter's full text unless the brief specifically calls for "
        "re-reading one for a callback."
    ),
    "system_prompt": (
        "You are a fiction writer. You were dispatched by another agent — "
        "you have no access to that conversation, only what's in this "
        "prompt. Draft only the chapter described in your brief, honoring "
        f"the dimension choices you were given. Read `{SKILLS_MOUNT}"
        "drafting-chapters/SKILL.md` if you need the conventions this "
        "dispatch follows. Do not dispatch your own subagents and do not "
        "review your own work against the spec — write the prose and "
        "return it."
    ),
    "skills": [SKILLS_MOUNT],
}

DIMENSION_REVIEWER_SUBAGENT: SubAgent = {
    "name": "dimension-reviewer",
    "description": (
        "Use to check a chapter or full story draft against its dimension "
        "spec and plan, per the reviewing-story-dimensions skill. Give it "
        "the draft, the spec (and Source Relationship section if this is "
        "an adaptation), and the relevant chapter brief or the whole plan "
        "for a final pass."
    ),
    "system_prompt": (
        "You are a dimension-coverage reviewer. You were dispatched by "
        "another agent — you have no access to that conversation, only "
        "what's in this prompt. Check the draft you were given against "
        "the spec/plan commitments you were given, per sub-dimension: "
        "Covered / Partial / Missing, each with a one-line note. Read "
        f"`{SKILLS_MOUNT}reviewing-story-dimensions/SKILL.md` for the full "
        f"checklist and severity ordering, and the relevant `{SKILLS_MOUNT}"
        "story-brainstorming/references/` or "
        f"`{SKILLS_MOUNT}adapting-existing-work/references/` file if you "
        "need a fuller definition of a sub-dimension while checking "
        "coverage. Report findings only; do not rewrite the prose yourself."
    ),
    "skills": [SKILLS_MOUNT],
}


def build_model(settings: Settings) -> Any:
    """Build the main-loop chat model from settings, with an optional rate limiter."""
    rate_limiter = None

    if settings.rate_limiter.enable_rate_limiter:
        rate_limiter = InMemoryRateLimiter(
            requests_per_second=settings.rate_limiter.requests_per_second,
            check_every_n_seconds=settings.rate_limiter.check_every_n_seconds,
            max_bucket_size=settings.rate_limiter.max_bucket_size,
        )

    return init_chat_model(model=settings.agent.orchestration_model_name, rate_limiter=rate_limiter)


def _with_skills_mounted(base_backend: BackendProtocol, skills_dir: str | Path) -> BackendProtocol:
    """Wrap `base_backend` so `SKILLS_MOUNT` resolves to the vendored skills dir.

    If `base_backend` is already a `CompositeBackend`, its existing routes
    are preserved and `SKILLS_MOUNT` is added alongside them (unless the
    caller already routed that exact prefix somewhere else, which is
    treated as intentional and left alone).
    """
    skills_backend = FilesystemBackend(root_dir=str(skills_dir))

    if isinstance(base_backend, CompositeBackend):
        if SKILLS_MOUNT in base_backend.routes:
            return base_backend
        routes = dict(base_backend.routes)
        routes[SKILLS_MOUNT] = skills_backend
        return CompositeBackend(
            default=base_backend.default,
            routes=routes,
            artifacts_root=base_backend.artifacts_root,
        )

    return CompositeBackend(default=base_backend, routes={SKILLS_MOUNT: skills_backend})


def build_backend(settings: Settings) -> BackendProtocol:
    """Build the project-files backend from settings, with skills mounted.

    Uses `LocalShellBackend` (unsandboxed local shell) instead of the plain
    `FilesystemBackend` only if `settings.backend.enable_shell` is set —
    none of the psalm-saga skills need shell access, so this stays off by
    default; the filesystem tools are unaffected either way.
    """
    if settings.backend.enable_shell:
        project_backend: BackendProtocol = LocalShellBackend(
            root_dir=str(settings.backend.root_dir)
        )
    else:
        project_backend = FilesystemBackend(root_dir=str(settings.backend.root_dir))

    return _with_skills_mounted(project_backend, SKILLS_DIR)


def build_agent(
    settings: Settings | None = None,
    *,
    tools: Sequence[Any] | None = None,
    system_prompt: str = "",
    subagents: Sequence[SubAgent] | None = None,
    checkpointer: Any = None,
    **create_deep_agent_kwargs: Any,
) -> CompiledStateGraph:
    """Construct the compiled psalm-saga deep agent.

    Args:
        settings: Application settings. Defaults to `Settings()` (reading
            from environment variables / a loaded `.env` file).
        tools: Extra custom tools beyond the built-in filesystem/subagent/
            to-do tools (e.g. a web-research tool, for fact-checking a
            historical-fiction setting).
        system_prompt: Your own instructions, if any. The psalm-saga
            bootstrap is appended after this.
        subagents: Additional named subagents beyond `chapter-writer` and
            `dimension-reviewer`, which are always registered.
        checkpointer: Passed to `create_deep_agent`. Defaults to `None`,
            in which case an in-memory `InMemorySaver` is provisioned so a
            multi-turn CLI session keeps conversation state across turns
            within the same `thread_id` — note `checkpointer=True` (the
            shorthand LangGraph offers) only works for *subgraphs*, not the
            root graph `create_deep_agent` returns, so an actual saver
            instance is required here. Pass your own `BaseCheckpointSaver`
            (e.g. a SQLite- or Postgres-backed one) for persistence across
            separate `psalm-saga` invocations.
        **create_deep_agent_kwargs: Passed straight through to
            `create_deep_agent` (e.g. `permissions=`, `interrupt_on=`).

    Returns:
        The compiled `CompiledStateGraph` from `create_deep_agent`.

    """
    settings = settings or Settings()
    resolved_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    resolved_subagents: list[SubAgent] = [
        {**CHAPTER_WRITER_SUBAGENT, "model": settings.agent.subagent_model_name},
        {**DIMENSION_REVIEWER_SUBAGENT, "model": settings.agent.subagent_model_name},
        *(subagents or []),
    ]

    full_system_prompt = compose_system_prompt(application_prompt=system_prompt)

    middleware = list(create_deep_agent_kwargs.pop("middleware", ()))
    middleware.append(TodoListMiddleware())
    middleware.extend(init_middleware(settings))

    return create_deep_agent(
        model=build_model(settings),
        tools=list(tools or []),
        system_prompt=full_system_prompt,
        skills=[SKILLS_MOUNT],
        backend=build_backend(settings),
        subagents=resolved_subagents,
        middleware=middleware,
        checkpointer=resolved_checkpointer,
        **create_deep_agent_kwargs,
    )
