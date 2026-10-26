from __future__ import annotations

from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"
FAKE = ["models.default.name=fake/test"]


def dutch_novel(chapters: int = 30, words_per_chapter: int = 3400) -> str:
    """A long, multi-chapter Dutch text with a few recurring characters."""
    names = ["Geertje Bos", "Teun", "juffrouw Pel", "dominee Kalf"]
    sentences = [
        "{a} liep langs de dijk en dacht aan wat {b} gisteren had gezegd.",
        "Het regende al de hele ochtend, en in de keuken brandde de kachel.",
        "„Je moet niet zo veel piekeren,” zei {b} tegen {a}, maar het hielp niet.",
        "Toen de klok zes sloeg, stond {a} op en trok de jas aan.",
        "Niemand in het dorp wist dat {b} die brief had verstopt.",
    ]
    out = []
    for c in range(1, chapters + 1):
        out.append(f"Hoofdstuk {c}")
        body, n, i = [], 0, 0
        while n < words_per_chapter:
            para = " ".join(
                sentences[(i + k) % len(sentences)].format(a=names[(c + k) % 4], b=names[(c + k + 1) % 4]) for k in range(5)
            )
            body.append(para)
            n += len(para.split())
            i += 1
        out.append("\n\n".join(body))
    return "\n\n".join(out)


@pytest.fixture
def runs(tmp_path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def nl_text() -> str:
    return (DATA / "nl_storm.txt").read_text(encoding="utf-8")
