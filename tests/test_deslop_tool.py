"""Tests for the mechanical AI-writing-tell and cross-chapter repetition scanner.

Pattern catalog ported from JuliusBrussee/skills' deslopify skill (references/tells.md). The
detection is deliberately mechanical (regex/arithmetic), not model judgment -- deslopify's own
core insight is that a model can't reliably self-detect its own statistical fingerprints, since
the same priors that generate a pattern also govern how the model judges it on review. Mirrors
gate.py's PROCEED/BLOCKED pattern: findings are computed here, and only the triage of what to do
about them is left to deslop-agent.
"""

from psalm_saga.tools.deslop import (  # type: ignore[import-untyped]
    find_repeated_phrases,
    format_findings,
    scan_ai_tells,
    scan_text,
)


def test_detects_puffery_vocabulary() -> None:
    text = "The lighthouse boasts a rich cultural heritage that seamlessly resonates with visitors."
    categories = {f.category for f in scan_text(text)}
    assert "puffery" in categories


def test_detects_negative_parallelism() -> None:
    text = "This isn't just a lighthouse, it's a monument to everyone who never came home."
    categories = {f.category for f in scan_text(text)}
    assert "negative_parallelism" in categories


def test_detects_hedging() -> None:
    text = "It's worth noting that the tide comes in fast here. At its core, the danger is timing."
    categories = {f.category for f in scan_text(text)}
    assert "hedging" in categories


def test_detects_rule_of_three() -> None:
    text = "Before the climb she packed rope, matches, and knives."
    categories = {f.category for f in scan_text(text)}
    assert "rule_of_three" in categories


def test_detects_em_dash_density() -> None:
    text = (
        "The door creaked — not from age, but from something pushing back — and Mara froze, "
        "her hand still on the handle — waiting."
    )
    categories = {f.category for f in scan_text(text)}
    assert "em_dash_density" in categories


def test_detects_uniform_sentence_length() -> None:
    text = (
        "The child ran through the tall grass near the fence. "
        "The sun was warm against the child's bare arms today. "
        "Birds called out from the trees above the field. "
        "The wind moved softly through the waving green stalks."
    )
    categories = {f.category for f in scan_text(text)}
    assert "uniform_sentence_length" in categories


def test_clean_varied_prose_produces_no_findings() -> None:
    text = (
        "Mara hated the fog. It hid the rocks until the hull was already over them, and by "
        "then it didn't matter how good a sailor you were -- you'd already lost. She'd told her "
        "father that once. He laughed, not unkindly, and said the fog wasn't the thing to hate."
    )
    assert scan_text(text) == []


def test_find_repeated_phrases_detects_shared_ngram() -> None:
    a = "A group of Quokkas, their shiny eyes gleaming with mischief, peeked out from the bushes."
    b = "Peeking out were a group of Quokkas, their shiny eyes gleaming with mischief once more."
    shared = find_repeated_phrases(a, b, min_words=5)
    assert any("shiny eyes gleaming with mischief" in phrase for phrase in shared)


def test_find_repeated_phrases_ignores_short_overlap() -> None:
    a = "The child ran through the grass."
    b = "A different child sat in the grass."
    assert find_repeated_phrases(a, b, min_words=5) == []


def test_scan_text_with_compare_against_flags_repeated_phrase() -> None:
    previous_chapter = (
        "On a vibrant, sun-soaked afternoon, laughter echoed through the air as a playful "
        "child ran through the untamed grass, exuberant and free."
    )
    this_chapter = (
        "On a sunlit afternoon, the vibrant colors of nature painted a backdrop as laughter "
        "echoed through the air as a playful child ran through the untamed grass once again."
    )
    findings = scan_text(this_chapter, compare_against=previous_chapter)
    assert any(f.category == "repeated_phrase" for f in findings)


def test_scan_text_detects_cross_chapter_repetition_in_assembled_draft() -> None:
    draft = (
        "# Quokka Quest\n\n"
        "## Chapter 1: The Friendly Encounter\n\n"
        "A group of Quokkas, their shiny eyes gleaming with mischief, peeked out from the "
        "bushes.\n\n"
        "## Chapter 2: Quokka Curiosity\n\n"
        "Peeking out were a group of Quokkas, their shiny eyes gleaming with mischief once "
        "more.\n"
    )
    findings = scan_text(draft)
    assert any(f.category == "cross_chapter_repetition" for f in findings)


def test_scan_text_single_chapter_text_skips_cross_chapter_check() -> None:
    text = "Just one chapter's worth of ordinary prose, no heading markers at all here."
    assert not any(f.category == "cross_chapter_repetition" for f in scan_text(text))


def test_format_findings_empty_returns_no_findings_message() -> None:
    assert "no" in format_findings([]).lower()


def test_format_findings_lists_each_finding() -> None:
    findings = scan_text(
        "This isn't just prose, it's a rich tapestry of testament to seamless craft."
    )
    message = format_findings(findings)
    assert str(len(findings)) in message
    for f in findings:
        assert f.category in message


def test_scan_ai_tells_tool_is_invokable() -> None:
    result = scan_ai_tells.invoke(
        {"text": "This isn't just a lighthouse, it's a monument.", "compare_against": ""}
    )
    assert isinstance(result, str)
    assert "negative_parallelism" in result


def test_scan_ai_tells_tool_clean_text_reports_no_findings() -> None:
    result = scan_ai_tells.invoke(
        {
            "text": (
                "Mara hated the fog. It hid the rocks until the hull was already over them."
            ),
            "compare_against": "",
        }
    )
    assert "no" in result.lower()
