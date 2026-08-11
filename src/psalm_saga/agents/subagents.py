from pathlib import Path

from deepagents import SubAgent

from psalm_saga.config import Settings
from psalm_saga.prompts import load_prompt
from psalm_saga.tools import (
    BIBLE_WRITE_PROTECTION,
    make_ask_human_tool,
    make_check_fidelity_tool,
    make_update_chapter_tool,
    make_update_story_bible_tool,
    make_validate_bible_tool,
    think,
)


def build_subagents(settings: Settings, session_dir: Path, *, non_interactive: bool = False) -> list[SubAgent]:
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
    :param non_interactive: Whether the subagents should operate in non-interactive mode.
    :type non_interactive: bool
    :return: A list of SubAgent instances, each configured with a name,
        description, tools, system prompt, and model to perform specific story
        generation tasks.
    :rtype: list[SubAgent]
    """
    model = settings.resolved_subagent_model()
    update_story_bible = make_update_story_bible_tool(session_dir)
    validate_story_bible = make_validate_bible_tool(session_dir)
    check_fidelity_alignment = make_check_fidelity_tool(session_dir)
    update_chapter = make_update_chapter_tool(session_dir)
    ask_human = make_ask_human_tool(non_interactive=non_interactive)

    extractor: SubAgent = {
        "name": "extractor-agent",
        "description": (
            "Reads a source text and populates story_bible.json from it, extracting the six "
            "PSALM dimensions (writing style, narrative voice, characters, plot, scenes, "
            "world building). Use once per session, at the start of from_source mode."
        ),
        "system_prompt": load_prompt("extractor"),
        "tools": [think, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    brainstorm: SubAgent = {
        "name": "brainstorm-agent",
        "description": (
            "Brainstorms the story with the user as a creative collaborator -- proposing "
            "concrete ideas and building on their answers, one question at a time -- to fill in "
            "or refine story_bible.json, or to negotiate a divergence_plan in from_source mode, "
            "or to resolve specific originality-guard findings in from_scratch mode. In "
            "non-interactive sessions, makes autonomous decisions instead of asking."
        ),
        "system_prompt": load_prompt("brainstorm"),
        "tools": [think, ask_human, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    originality_guard: SubAgent = {
        "name": "originality-guard",
        "description": (
            "Reviews story_bible.json (from_scratch mode only) for parody, pastiche, "
            "quotation, scenes-a-faire, and general resemblance to identifiable existing "
            "works, recording findings in the bible."
        ),
        "system_prompt": load_prompt("originality_guard"),
        "tools": [think, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    chapter_planner: SubAgent = {
        "name": "chapter-planner-agent",
        "description": (
            "Runs once, after the bible is finalized and before any chapter is drafted: turns "
            "story_bible.json into a chapter-by-chapter outline (the `chapters` list) sized to "
            "length_tier, and sets the book title if brainstorm-agent left it unset."
        ),
        "system_prompt": load_prompt("chapter_planner"),
        "tools": [think, update_story_bible, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    writer: SubAgent = {
        "name": "writer-agent",
        "description": (
            "Drafts one chapter at a time to chapters/chapter_<NN>.md, given that chapter's "
            "outline entry in story_bible.json's chapters list and bounded continuity context "
            "(the previous chapter in full, running actual_summary of earlier chapters). "
            "Delegated once per chapter, and again for any revision pass."
        ),
        "system_prompt": load_prompt("writer"),
        "tools": [think],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    chapter_reviewer: SubAgent = {
        "name": "chapter-reviewer-agent",
        "description": (
            "Runs once per chapter (and again per revision): reviews a just-drafted chapter "
            "(chapters/chapter_<NN>.md) against the outline, the previous chapter, and earlier "
            "chapters' actual_summary for prose quality, continuity, and fit against its "
            "planned_summary. Approves (recording actual_summary + status=approved) or returns "
            "specific revision notes for writer-agent."
        ),
        "system_prompt": load_prompt("chapter_reviewer"),
        "tools": [think, update_chapter, validate_story_bible],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }

    editor: SubAgent = {
        "name": "editor-agent",
        "description": (
            "Reviews draft.md against story_bible.json for consistency, fidelity, and prose "
            "quality, writes the polished result to final_story.md, and (from_source mode) "
            "records achieved_divergence and runs the fidelity-alignment check."
        ),
        "system_prompt": load_prompt("editor"),
        "tools": [think, update_story_bible, check_fidelity_alignment],
        "model": model,
        "permissions": BIBLE_WRITE_PROTECTION,
    }



    return [
        extractor,
        brainstorm,
        originality_guard,
        chapter_planner,
        writer,
        chapter_reviewer,
        editor,
    ]