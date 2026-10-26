import io
import json
import zipfile

from fastapi.testclient import TestClient

from psalm_saga.pipeline import Pipeline
from psalm_saga.web.app import create_app
from tests.conftest import FAKE


async def test_full_and_release_bundles(runs, nl_text):
    p = Pipeline.create("full", runs_dir=runs, source=nl_text, overrides=FAKE, run_id="b1")
    await p.run()
    from psalm_saga.bundle import build_bundle

    full = zipfile.ZipFile(io.BytesIO(build_bundle(p.store.root)))
    names = set(full.namelist())
    assert {"input/source.txt", "story.md", "evaluation.json", "README.md", "graph-synthetic.graphml"} <= names
    assert "graph-source.graphml" in names and "CONTAINS THE SOURCE TEXT" in full.read("README.md").decode()

    rel = zipfile.ZipFile(io.BytesIO(build_bundle(p.store.root, release=True)))
    rnames = set(rel.namelist())
    assert "story.md" in rnames and "spec.json" in rnames and "graph-synthetic.graphml" in rnames
    for banned in ("input/source.txt", "bible_source.json", "spec_source.json", "transform.json", "profile.json",
                   "events.jsonl", "graph-source.graphml", "guard.json"):
        assert banned not in rnames, banned
    assert not any(n.startswith("notes/") for n in rnames)
    ev = json.loads(rel.read("evaluation.json"))
    assert all("text" not in s for s in ev["leakage"]["copied_spans"])
    assert all("name" not in r for r in ev.get("distributions", {}).get("characters", []))
    # No sentence of the source survives anywhere in the release bundle.
    src_sentences = [s for s in nl_text.split(".") if len(s.split()) >= 12][:20]
    blob = " ".join(rel.read(n).decode("utf-8", "ignore") for n in rnames)
    assert not any(s.strip() in blob for s in src_sentences)


def test_bundle_endpoint_and_chapter_paths(tmp_path, nl_text):
    import asyncio

    p = Pipeline.create("no_review", runs_dir=tmp_path, source=nl_text, overrides=FAKE, run_id="b2")
    asyncio.run(p.run())
    with TestClient(create_app(tmp_path)) as c:
        st = c.get("/api/runs/b2").json()
        assert "chapters/ch_001.json" in st["artifacts"]  # forward slashes on every OS (Chapters tab)
        r = c.get("/api/runs/b2/bundle?kind=release")
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        assert "story.md" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
