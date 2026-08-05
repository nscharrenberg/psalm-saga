from psalm_saga.config import Settings  # type: ignore[import-untyped]


def test_chapter_review_max_revisions_defaults_to_two(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    assert settings.chapter_review_max_revisions == 2


def test_chapter_review_max_revisions_overridable_via_env(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PSALM_SAGA_CHAPTER_REVIEW_MAX_REVISIONS", "5")
    settings = Settings(model="anthropic:claude-opus-4-8", sessions_root=tmp_path)
    assert settings.chapter_review_max_revisions == 5
