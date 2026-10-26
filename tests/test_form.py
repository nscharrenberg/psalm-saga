from psalm_saga.store import RunStore
from psalm_saga.text.chunking import split_chapters
from psalm_saga.text.form import form_brief, form_metrics, form_profile, verse_sections
from psalm_saga.text.metrics import paragraphs, stylometrics
from psalm_saga.text.style import rhythm_scaffold, shape
from tests.conftest import DATA

VERSE = (DATA / "nl_verse.txt").read_text(encoding="utf-8")


def test_crlf_and_double_cr_are_normalised(tmp_path):
    st = RunStore(tmp_path / "r")
    st.write_text("a.txt", "regel een\r\nregel twee\r\n\r\nstrofe twee")
    assert st.read_text("a.txt") == "regel een\nregel twee\n\nstrofe twee"
    (tmp_path / "r" / "b.txt").write_bytes(b"een\r\r\ntwee\r\r\n\r\r\ndrie")  # what Windows text mode made of CRLF
    assert st.read_text("b.txt") == "een\ntwee\n\ndrie"


def test_verse_is_detected_with_its_form():
    fp = form_profile(VERSE)
    assert fp["form"] == "verse" and fp["rhyme_scheme"] == "AABB" and fp["rhyme_share"] > 0.6
    assert fp["lines_per_stanza_mode"] == 4 and 4 <= fp["line_words_mean"] <= 8 and fp["poem_titles"] == 3
    assert [t for t, _ in verse_sections(VERSE)] == ["De natte kat", "De trage Teun", "Het brave Liesje"]
    chs = split_chapters(VERSE)
    assert len(chs) == 3 and chs[0].title == "De natte kat"
    assert "VERSE" in form_brief(fp) and "couplets" in form_brief(fp)
    prose = " ".join(line.strip() for line in VERSE.splitlines() if line.strip())
    assert form_metrics(prose)["form"] == "prose"


def test_prose_stays_prose_in_every_test_language():
    for f in ("nl_storm.txt", "en_ledger.txt", "de_muehle.txt", "nl_brieven.txt", "nl_archaic.txt", "en_harbour.txt"):
        assert form_profile((DATA / f).read_text(encoding="utf-8"))["form"] == "prose", f


def test_line_paragraphs_and_page_breaks():
    one_per_line = "\n".join(f"Dit is alinea {i} met een hele reeks woorden die samen een volledige zin vormen hier." for i in range(10))
    assert len(paragraphs(one_per_line)) == 10
    paged = "Het meisje liep naar de put en\n\nzag daar haar spiegelbeeld. Zij schrok.\n\nToen ging zij naar huis."
    assert len(paragraphs(paged)) == 2  # the break inside the first sentence is a page break


def test_rhythm_scaffold_follows_source_paragraphs():
    src = (DATA / "nl_archaic.txt").read_text(encoding="utf-8")
    sh = shape(src)
    sc = rhythm_scaffold(sh, 400, 0.5)
    assert sc.startswith("Rhythm scaffold") and "P1:" in sc
    total = sum(int(x) for line in sc.splitlines()[1:] for x in line.split(":")[1].replace("[speech]", "").split("·"))
    assert 350 <= total <= 520
    assert stylometrics(src, "nl")["dialogue_word_share"] >= 0


async def test_verse_source_end_to_end(runs):
    import json

    from psalm_saga.pipeline import Pipeline
    from tests.conftest import FAKE

    p = Pipeline.create("full", runs_dir=runs, source=VERSE, run_id="verse",
                        overrides=[*FAKE, "models.default.extra.fake_follow_form=true"])
    await p.run()
    prof = p.store.read_json("profile.json")
    assert prof["form"]["form"] == "verse" and len(prof["chapters"]) == 3
    ev = p.store.read_json("evaluation.json")
    assert ev["form"]["source"] == "verse" and ev["form"]["synthetic"] == "verse" and ev["form"]["match"] == 1.0
    assert ev["fidelity"]["chapter_count_match"] == 1.0
    story = p.store.read_text("story.md")
    assert "Hoofdstuk" not in story  # poems carry titles, not chapter numbers
    logs = [json.loads(f.read_text(encoding="utf-8")) for f in p.store.glob("conform/ch_*.json")]
    assert logs and all(log["form"] == "verse" for log in logs)


async def test_prose_drafted_for_verse_is_retried(runs):
    from psalm_saga.pipeline import Pipeline
    from tests.conftest import FAKE

    p = Pipeline.create("full", runs_dir=runs, source=VERSE, run_id="verse2", overrides=FAKE)
    await p.run()
    assert any(e["type"] == "form_mismatch" for e in p.store.events())
    assert p.store.read_json("evaluation.json")["form"]["match"] == 0.0  # and the evaluation says so
