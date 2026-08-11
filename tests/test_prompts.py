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


def test_chapter_reviewer_prompt_uses_update_chapter_not_raw_patches() -> None:
    """Regression test for the chapter-index corruption bug: chapter-reviewer-agent used to
    compose raw RFC 6902 patches against `/chapters/<index-1>/...`, and got the array-position
    arithmetic wrong in production, then "fixed" its own test-op guard failure by overwriting the
    guarded `index` field -- turning one chapter into a duplicate of another. The prompt must
    route approvals through `update_chapter` (which finds a chapter by its own `index` field, not
    array position) and must no longer teach the array-position-arithmetic pattern at all."""
    text = load_prompt("chapter_reviewer")
    assert "update_chapter" in text
    assert "actual_summary" in text
    assert "array position" not in text.lower()
    assert '"op": "replace", "path": "/chapters/' not in text


def test_chapter_reviewer_prompt_reads_chapters_via_read_chapter_file() -> None:
    """Same root cause as the writer-side fix: the reviewer's own prompt used to spell out
    literal paths (`chapters/chapter_<NN>.md`, `chapters/chapter_<NN-1>.md`) that it had to
    construct itself. `read_chapter_file(index=...)` removes that construction step."""
    text = load_prompt("chapter_reviewer")
    assert "read_chapter_file" in text


def test_writer_prompt_drafts_one_chapter_not_the_full_story() -> None:
    text = load_prompt("writer")
    assert "write the full story" not in text
    assert "chapters/chapter_" in text


def test_writer_prompt_uses_index_addressed_chapter_file_tool() -> None:
    """Regression test for the root cause of the two-different-drafts-per-chapter bug: the
    orchestrator's own delegation text named `chapters/chapter_1.md` (unpadded) for chapter 1,
    writer-agent wrote there literally via the generic write_file tool, and a later retry (after
    assemble_draft correctly reported it missing under the padded name) produced a second,
    different draft at the correctly-padded `chapters/chapter_01.md`. `write_chapter_file` takes
    the chapter's own `index` integer and computes the canonical filename internally -- the
    prompt must route through it instead of telling the writer to pick between write_file and
    edit_file (both now permission-blocked on chapters/*.md anyway)."""
    text = load_prompt("writer")
    assert "write_chapter_file" in text
    assert "read_chapter_file" in text
    assert "use\n`edit_file`" not in text
    assert "always overwrites" in text.lower() or "overwrites unconditionally" in text.lower()


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


def test_orchestrator_prompt_uses_update_chapter_for_revision_count() -> None:
    """Regression test: the orchestrator previously bumped a chapter's revision_count via raw
    `update_story_bible` patches against `/chapters/<n>/revision_count`, computing the array
    position itself -- and, in production, used the wrong position (writing "Chapters 1 and 2"
    updates to positions 1 and 2, when 0-based positions 0 and 1 were correct), silently
    corrupting a different chapter's data each time. `update_chapter`'s `increment_revision_count`
    removes both the position arithmetic and the need to track/pass an absolute count."""
    text = load_prompt("orchestrator")
    assert "update_chapter" in text
    assert "increment_revision_count" in text


def test_orchestrator_prompt_never_writes_a_chapter_filename_itself() -> None:
    """Regression test for the actual root cause of the two-different-drafts-per-chapter bug:
    the orchestrator's own delegation text (composed in its own prose, not copied from anywhere)
    read "Draft Chapter 1 titled 'The Artifact' to chapters/chapter_1.md" -- unpadded, because
    orchestrator.md never stated the padding convention at all (only writer.md did). Since
    writer-agent now derives its output path from the chapter's `index` via `write_chapter_file`,
    the orchestrator's delegation instructions must no longer tell it to compose a
    `chapters/chapter_<NN>.md`-shaped path in its own delegation text."""
    text = load_prompt("orchestrator")
    assert "to `chapters/chapter_<NN>.md`" not in text
    assert "write_chapter_file" in text or "read_chapter_file" in text


def test_orchestrator_prompt_forbids_parallel_chapter_delegation() -> None:
    """Regression test for InvalidUpdateError: At key 'mode' -- the orchestrator delegated
    writer-agent for three chapters in a single turn (deepagents' base prompt encourages
    parallelizing independent-looking tasks), which is wrong on two counts: it crashes on any
    unreduced custom state field two concurrent subagent invocations both happen to touch, and
    even when it doesn't crash it silently breaks continuity, since chapter N's writer-agent is
    supposed to read chapter N-1's actual finished text, which doesn't exist yet if they run
    concurrently. The prompt must say so explicitly, not just imply it via "in order"."""
    text = load_prompt("orchestrator")
    assert "parallel" in text.lower()
    assert "one chapter at a time" in text.lower() or "never issue multiple" in text.lower()
