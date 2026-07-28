from pathlib import Path

from deepagents import SubAgent

from psalm_saga.config import Settings
from psalm_saga.prompts import load_prompt
from psalm_saga.tools import make_validate_bible_tool, think, ask_human


def build_subagents(settings: Settings, session_dir: Path) -> list[SubAgent]:
    """
    Builds a list of SubAgent configurations required for different tasks in the
    story generation process. Each SubAgent is configured with specific tools,
    prompts, and associated descriptions to handle tasks like text extraction,
    brainstorming, originality checks, story drafting, and editing.

    :param settings: A configuration object containing user-defined or default
        settings for subagent models and operations.
    :type settings: Settings
    :param session_dir: A directory path used for temporary or persistent
        session-related data, such as generated files and tools.
    :type session_dir: Path
    :return: A list of SubAgent instances, each configured with a name,
        description, tools, system prompt, and model to perform specific story
        generation tasks.
    :rtype: list[SubAgent]
    """
    model = settings.resolved_subagent_model()
    validate_story_bible = make_validate_bible_tool(session_dir)

    extractor: SubAgent = {
        "name": "extractor-agent",
        "description": (
            "Reads a source text and populates story_bible.json from it, extracting the six "
            "PSALM dimensions (writing style, narrative voice, characters, plot, scenes, "
            "world building). Use once per session, at the start of from_source mode."
        ),
        "system_prompt": load_prompt("extractor"),
        "tools": [think, validate_story_bible],
        "model": model,
    }

    brainstorm: SubAgent = {
        "name": "brainstorm-agent",
        "description": (
            "Converses with the user, one question at a time, to fill in or refine "
            "story_bible.json, or to negotiate a divergence_plan in from_source mode, or to "
            "resolve specific originality-guard findings in from_scratch mode."
        ),
        "system_prompt": load_prompt("brainstorm"),
        "tools": [think, ask_human, validate_story_bible],
        "model": model,
    }

    originality_guard: SubAgent = {
        "name": "originality-guard",
        "description": (
            "Reviews story_bible.json (from_scratch mode only) for parody, pastiche, "
            "quotation, scenes-a-faire, and general resemblance to identifiable existing "
            "works, recording findings in the bible."
        ),
        "system_prompt": load_prompt("originality_guard"),
        "tools": [think, validate_story_bible],
        "model": model,
    }

    writer: SubAgent = {
        "name": "writer-agent",
        "description": (
            "Drafts the full story in draft.md from a finalized story_bible.json (and, in "
            "from_source mode, the divergence_plan and source text)."
        ),
        "system_prompt": load_prompt("writer"),
        "tools": [think],
        "model": model,
    }

    editor: SubAgent = {
        "name": "editor-agent",
        "description": (
            "Reviews draft.md against story_bible.json for consistency, fidelity, and prose "
            "quality, and writes the polished result to final_story.md."
        ),
        "system_prompt": load_prompt("editor"),
        "tools": [think],
        "model": model,
    }

    return [
        extractor,
        brainstorm,
        originality_guard,
        writer,
        editor,
    ]