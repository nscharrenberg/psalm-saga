from psalm_saga.dimensions import LENGTH_TIER_SPECS  # type: ignore[import-untyped]
from psalm_saga.prompts import load_prompt  # type: ignore[import-untyped]


def test_extractor_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("extractor")
    assert '"op": "replace"' in text
    assert '"op": "add"' in text
    assert "deep-merged" not in text


def test_brainstorm_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("brainstorm")
    assert '"op": "replace"' in text
    assert '"op": "test"' in text
    assert "replaced wholesale" not in text


def test_originality_guard_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("originality_guard")
    assert '"op": "add"' in text
    assert "replaces the field wholesale" not in text


def test_editor_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("editor")
    assert '"op": "add"' in text
    assert "pass the complete list" not in text


def test_chapter_planner_prompt_documents_json_patch_ops_and_title_guidance() -> None:
    text = load_prompt("chapter_planner")
    assert '"op": "add"' in text
    assert "Quokka Quest" in text


def test_chapter_reviewer_prompt_documents_json_patch_ops() -> None:
    text = load_prompt("chapter_reviewer")
    assert '"op": "replace"' in text
    assert "actual_summary" in text


def test_writer_prompt_drafts_one_chapter_not_the_full_story() -> None:
    text = load_prompt("writer")
    assert "write the full story" not in text
    assert "chapters/chapter_" in text


def test_brainstorm_prompt_requires_title_proposal_not_optional() -> None:
    text = load_prompt("brainstorm")
    assert "fine to leave unsettled going into the writing stage" not in text
    assert "Titling the book" in text
    assert "Quokka Quest" in text


def test_chapter_planner_prompt_length_tier_table_matches_length_tier_specs() -> None:
    """LENGTH_TIER_SPECS (dimensions.py) is never read by production code -- chapter_planner.md's
    prose table is the only place the tier numbers actually take effect. Assert the numbers can't
    silently drift apart."""
    text = load_prompt("chapter_planner")

    for tier, spec in LENGTH_TIER_SPECS.items():
        chapters = (
            str(spec.min_chapters)
            if spec.min_chapters == spec.max_chapters
            else f"{spec.min_chapters}-{spec.max_chapters}"
        )
        words = f"~{spec.target_total_words:,}"
        assert chapters in text, f"{tier.value} tier's chapter range {chapters!r} not in prompt"
        assert words in text, f"{tier.value} tier's word target {words!r} not in prompt"


def test_orchestrator_prompt_documents_chapter_writing_loop() -> None:
    text = load_prompt("orchestrator")
    assert "draft the full story from the finalized bible" not in text
    assert "chapter-planner-agent" in text
    assert "chapter-reviewer-agent" in text
    assert "assemble_draft" in text
