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
