import json
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from psalm_saga.artifacts import Bible
from psalm_saga.cli.main import app
from psalm_saga.graph import build_graph, to_graphml
from psalm_saga.pipeline import Pipeline
from psalm_saga.web.app import create_app
from tests.conftest import DATA, FAKE

BIBLE = Bible.model_validate_json((DATA / "bible_demo.json").read_text(encoding="utf-8"))


def edges(g, typ):
    return [e for e in g["edges"] if e["type"] == typ]


def test_graph_covers_world_scenes_and_events():
    g = build_graph(BIBLE)
    assert g["counts"] == {"character": 5, "place": 4, "object": 1, "organisation": 1, "chapter": 4, "scene": 9, "event": 11}
    rel = edges(g, "relation")
    assert {e["group"] for e in rel} == {"social", "world"}
    assert any(e["label"] == "lives in" or e["label"] == "woont in" for e in rel)
    # scenes resolve to their place, by location or by a place named in the setting
    set_in = {(e["source"], e["target"]) for e in edges(g, "set_in")}
    assert ("s1.1", "e7") in set_in and ("s4.1", "e8") in set_in
    # aliases and first names resolve to the right character
    appears = {(e["source"], e["target"]) for e in edges(g, "appears_in")}
    assert ("e1", "s1.2") in appears  # "Geertje" -> Geertje Bos
    assert ("e2", "s2.2") in appears  # "Teun" -> Teun Wit


def test_causal_chain_explicit_and_inferred():
    causes = {(e["source"], e["target"]): e["inferred"] for e in edges(build_graph(BIBLE), "causes")}
    assert causes[("v1.1", "v1.2")] is False  # cause_index inside a chapter
    assert causes[("v1.3", "v3.1")] is True  # cause given as text, two chapters later
    assert causes[("v3.2", "v4.1")] is True
    assert all(int(s[1]) <= int(t[1]) for s, t in causes)  # causes never point back in time


def test_cooccurrence_counts_shared_scenes():
    co = {tuple(sorted((e["source"], e["target"]))): e for e in edges(build_graph(BIBLE), "co_occurs")}
    assert co[("e1", "e2")]["weight"] == 3  # Geertje and Teun share scenes 1.1, 2.1 and 4.1
    assert co[("e1", "e2")]["chapters"] == [1, 2, 4]
    assert co[("e1", "e2")]["directed"] is False


def test_counterpart_and_graphml():
    g = build_graph(BIBLE, counterpart={"Geertje Bos": "Hilde Vos"})
    node = next(n for n in g["nodes"] if n["id"] == "e1")
    assert node["details"]["counterpart"] == "Hilde Vos"
    root = ET.fromstring(to_graphml(g))
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    assert len(root.findall(".//g:node", ns)) == len(g["nodes"])
    assert len(root.findall(".//g:edge", ns)) == len(g["edges"])


def test_graph_without_scene_casts_falls_back_to_chapters():
    b = BIBLE.model_copy(deep=True)
    for ch in b.chapters:
        for sc in ch.scenes:
            sc.characters = []
    co = edges(build_graph(b), "co_occurs")
    assert co and all(e["weight"] >= 1 for e in co)


def test_api_and_cli_export(tmp_path, nl_text):
    p = Pipeline.create("no_review", runs_dir=tmp_path, source=nl_text, overrides=FAKE, run_id="g1")
    p.store.write_json("bible.json", BIBLE)
    p.store.write_json("bible_source.json", BIBLE)
    with TestClient(create_app(tmp_path)) as c:
        g = c.get("/api/runs/g1/graph?which=synthetic").json()
        assert len(g["nodes"]) == 35
        r = c.get("/api/runs/g1/graph?which=source&format=graphml")
        assert r.status_code == 200 and r.text.startswith("<?xml")
        assert c.get("/static/kg.js").status_code == 200
        assert c.get("/static/vendor/cytoscape-3.34.4.min.js").status_code == 200
    res = CliRunner().invoke(app, ["graph", str(tmp_path / "g1"), "--format", "json"])
    assert res.exit_code == 0, res.output
    assert json.loads((tmp_path / "g1" / "graph-synthetic.json").read_text(encoding="utf-8"))["counts"]["event"] == 11


def test_compare_design_and_text():
    from psalm_saga.graph import compare_graphs
    from psalm_saga.stages.transform import rename_model

    mapping = {"Geertje Bos": "Aaltje Mol", "Teun Wit": "Gerrit Zwart", "Hoogwoude": "Lagerveen"}
    # Design: same ids, renamed; nothing removed -> everything kept.
    design = rename_model(BIBLE, mapping)
    cmp = compare_graphs(build_graph(BIBLE), build_graph(design), mapping)
    assert {n["status"] for n in cmp["nodes"]} == {"kept"}
    geertje = next(n for n in cmp["nodes"] if n["id"] == "e1")
    assert geertje["details"]["counterpart"] == "Aaltje Mol"
    assert cmp["summary"]["nodes"]["character"]["recall"] == 1.0

    # "Text": independent ids; one character missing, one new, one relation relabelled.
    text = design.model_copy(deep=True)
    for e in text.entities:
        e.id = "t" + e.id
    for r in text.relations:
        r.source, r.target = "t" + r.source, "t" + r.target
    text.entities = [e for e in text.entities if e.name != "Dominee Kalf"]
    text.relations = [r for r in text.relations if r.source != "te4" and r.target != "te4"]
    from psalm_saga.artifacts import Entity, Relation

    text.entities.append(Entity(id="tx", name="Meester Rook", kind="character", chapters=[2]))
    text.relations[0] = Relation(source="te1", target="te5", type="dochter van")
    text.relations.append(Relation(source="tx", target="te1", type="leert"))
    cmp = compare_graphs(build_graph(BIBLE), build_graph(text), mapping)
    status = {n["label"]: n["status"] for n in cmp["nodes"] if n["type"] == "character"}
    assert status["Dominee Kalf"] == "source_only" and status["Meester Rook"] == "synthetic_only"
    assert status["Geertje Bos"] == "kept"
    rel = {(e["source"], e["target"], e["status"]) for e in cmp["edges"] if e["type"] == "relation"}
    assert ("e1", "e5", "changed") in rel and ("e4", "e2", "source_only") in rel and ("y:tx", "e1", "synthetic_only") in rel
    assert cmp["summary"]["nodes"]["character"]["recall"] == 0.8
    assert "status" in to_graphml(cmp)


def test_recover_and_compare_api(tmp_path, nl_text):
    import asyncio
    import time

    p = Pipeline.create("full", runs_dir=tmp_path, source=nl_text, overrides=FAKE, run_id="cmp")
    asyncio.run(p.run())
    # The full preset re-extracts the synthetic text as part of the run (stage `recover`).
    assert p.store.exists("recovered/bible_source.json")
    ev = p.store.read_json("evaluation.json")
    assert "structure" in ev and "character" in ev["structure"]["nodes"]
    with TestClient(create_app(tmp_path)) as c:
        g = c.get("/api/runs/cmp/graph?which=compare").json()
        assert g["compare"] and all("status" in n for n in g["nodes"])
        g = c.get("/api/runs/cmp/graph?which=compare&against=text").json()
        assert g["summary"]["nodes"] and "recovered/bible_source.json" in c.get("/api/runs/cmp").json()["artifacts"]
        assert c.get("/api/runs/cmp/graph?which=compare&against=text&format=graphml").status_code == 200
        assert c.post("/api/runs/cmp/recover").json()["status"] == "done"

    # A run made without the stage (stage disabled) can recover later, in the background.
    q = Pipeline.create("no_review", runs_dir=tmp_path, source=nl_text,
                        overrides=[*FAKE, "stages.recover.enabled=false"], run_id="late")
    asyncio.run(q.run())
    assert not q.store.exists("recovered/bible_source.json")
    with TestClient(create_app(tmp_path)) as c:
        assert c.get("/api/runs/late/graph?which=compare&against=text").status_code == 404
        assert c.post("/api/runs/late/recover").json()["status"] == "started"
        for _ in range(100):
            st = c.get("/api/runs/late").json()
            if "recovered/bible_source.json" in st["artifacts"] and st["status"] == "done":
                break
            time.sleep(0.1)
        assert st["status"] == "done"
        assert c.get("/api/runs/late/graph?which=compare&against=text").status_code == 200


def test_compare_text_pairs_objects_named_after_renamed_characters():
    """Two independent analyses: "George's chest" in the source must pair with "Nathaniel's chest"
    in the synthetic text when George -> Nathaniel, and differently worded objects of the same
    owner must pair through name words, description and shared neighbours."""
    from psalm_saga.graph import compare_graphs

    def bible(chars, objs, rels):
        return Bible.model_validate({
            "entities": [{"id": i, "name": n, "kind": "character", "chapters": [1], "mentions": 5} for i, n in chars]
            + [{"id": i, "name": n, "kind": k, "description": d, "chapters": [1], "mentions": 2} for i, n, k, d in objs],
            "relations": [{"source": a, "target": b, "type": t} for a, b, t in rels],
            "chapters": [{"index": 1, "title": "", "summary": "", "scenes": [], "events": []}]})

    src = build_graph(bible([("c1", "George Ballmer")],
                            [("o1", "George's chest", "object", "an old sea chest full of letters"),
                             ("o2", "the brass key", "object", "small key that opens the chest")],
                            [("c1", "o1", "owns"), ("c1", "o2", "carries")]))
    syn = build_graph(bible([("e1", "Nathaniel Brook")],
                            [("e2", "Nathaniel's chest", "object", "a sea chest holding letters"),
                             ("e3", "brass key", "other", "a key for the chest")],
                            [("e1", "e2", "possesses"), ("e1", "e3", "carries")]))
    g = compare_graphs(src, syn, {"George Ballmer": "Nathaniel Brook", "George": "Nathaniel", "Ballmer": "Brook"})
    st = {n["label"]: n["status"] for n in g["nodes"]}
    assert st["George's chest"] in ("kept", "changed") and "Nathaniel's chest" not in st
    assert st["the brass key"] in ("kept", "changed") and "brass key" not in st
    assert g["summary"]["nodes"]["object"]["source_only"] == 0
    rel = {e["label"]: e["status"] for e in g["edges"] if e["type"] == "relation"}
    assert rel["carries"] == "kept"


def test_compare_text_aligns_scenes_by_content_and_tolerates_noise():
    """A scene told in two parts must not shift every later scene to "changed"; plural/diminutive
    object names pair; a character classified as an object is a remark, not a change."""
    from psalm_saga.graph import _tok_match, compare_graphs

    def bible(scenes, objs, extra_ents=()):
        return Bible.model_validate({
            "entities": [{"id": "c1", "name": "Kaatje", "kind": "character", "chapters": [1], "mentions": 9},
                         {"id": "c2", "name": "moeder", "kind": "character", "chapters": [1], "mentions": 5}]
            + [{"id": f"o{i}", "name": n, "kind": "object", "chapters": [1], "mentions": 2} for i, n in enumerate(objs)]
            + list(extra_ents),
            "relations": [],
            "chapters": [{"index": 1, "title": "", "summary": "",
                          "scenes": [{"summary": s, "characters": c} for s, c in scenes], "events": []}]})

    src = build_graph(bible([("Kaatje morst bij het eten en moeder waarschuwt haar", ["Kaatje", "moeder"]),
                             ("moeder haalt drie biggetjes uit het hok", ["moeder"]),
                             ("Kaatje eet tussen de biggetjes en huilt", ["Kaatje"])],
                            ["de stok", "de twee snorren"]))
    syn = build_graph(bible([("Kaatje morst steeds bij het eten", ["Kaatje"]),
                             ("moeder waarschuwt Kaatje telkens weer", ["Kaatje", "moeder"]),   # first scene split in two
                             ("moeder haalt de biggetjes uit het hok", ["moeder"]),
                             ("Kaatje moet tussen de biggetjes eten en huilt", ["Kaatje"])],
                            ["De stokken", "De snorren"]))
    g = compare_graphs(src, syn, {})
    st = {n["id"]: n["status"] for n in g["nodes"] if n["type"] == "scene"}
    assert st == {"s1.1": "kept", "s1.2": "kept", "s1.3": "kept"}       # nothing shifted
    assert not [n for n in g["nodes"] if n["type"] == "scene" and n["status"] == "synthetic_only"]  # split part absorbed
    assert g["summary"]["nodes"]["object"]["source_only"] == 0
    assert _tok_match("stok", "stokken") and _tok_match("paard", "paardje") and not _tok_match("trommel", "trommelstok")
