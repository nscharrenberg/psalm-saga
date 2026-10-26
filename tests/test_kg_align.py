"""The synthetic text is aligned with the design (one analysis per text); the model pairs what names
cannot, and a check of the chapter finds what the analysis missed."""

from psalm_saga.artifacts import Bible
from psalm_saga.eval.kg_align import Check, Checks, Pair, Pairs, align_to_design


def _bible(chars, rels, events):
    return Bible.model_validate({
        "entities": [{"id": i, "name": n, "kind": "character", "chapters": [1], "mentions": 5, "description": d}
                     for i, n, d in chars],
        "relations": [{"source": a, "target": b, "type": t} for a, b, t in rels],
        "chapters": [{"index": 1, "summary": "", "scenes": [], "events": [{"description": e} for e in events]}]})


class ScriptedModel:
    """Stands in for the model: pairs the daughter by description, and confirms the relation in the text."""

    def __init__(self):
        self.tags = []

    async def json(self, role, role_text, parts, schema, **kw):
        tag = kw.get("tag", "")
        self.tags.append(tag)
        prompt = parts[-1].text
        if schema is Pairs and "align:entities" in tag:
            return Pairs(pairs=[Pair(a="e3", b="t3", confidence="high", reason="the widow's idle daughter")])
        if schema is Checks:
            ks = [line.split(".")[0] for line in prompt.splitlines() if "[relation]" in line]
            return Checks(items=[Check(item=k, realised="yes", evidence="haar stiefzuster Roeteke") for k in ks])
        return schema() if schema is not Pairs else Pairs()


async def test_model_pairs_and_text_check_relate_items_back():
    design = _bible([("e1", "Weduwe", "a widow"), ("e2", "Roeteke", "the diligent stepdaughter"),
                     ("e3", "Eigen dochter", "the widow's own, idle daughter")],
                    [("e1", "e3", "moeder van"), ("e2", "e3", "stiefzuster van")], ["Roeteke valt in de put"])
    text = _bible([("t1", "de weduwe", "widow"), ("t2", "Roeteke", "stepdaughter"),
                   ("t3", "het luie meisje", "spoilt girl who will not work")],   # nothing in common by name
                  [], ["Roeteke valt in de put"])                                  # the analysis found no relations
    m = ScriptedModel()
    res = await align_to_design(m, design, text, {1: "… haar stiefzuster Roeteke …"})
    pairs = {(p["design"], p["text"]): p["method"] for p in res["pairs"]}
    assert pairs[("e3", "t3")] == "model" and pairs[("e2", "t2")] == "rules"
    assert {"edge:relation:e1:e3", "edge:relation:e2:e3"} <= set(res["checks"])     # found by reading the chapter
    assert res["stats"]["model_entities"] == 1 and res["stats"]["found_by_check"] == 2

    from psalm_saga.graph import build_graph, compare_graphs

    g = compare_graphs(build_graph(design), build_graph(text), {}, prealign=[(p["design"], p["text"]) for p in res["pairs"]],
                       checks=res["checks"])
    st = {(e["source"], e["label"]): e["status"] for e in g["edges"] if e["type"] == "relation"}
    assert st[("e1", "moeder van")] == "kept" and st[("e2", "stiefzuster van")] == "kept"   # confirmed in the text
    assert {n["id"]: n["status"] for n in g["nodes"]}["e3"] == "kept"                         # paired by the model
    assert g["summary"]["edges"]["relation:social"]["recall"] == 1.0


def test_source_view_goes_through_the_design_ids(tmp_path):
    from psalm_saga.eval.kg_align import text_comparison
    from psalm_saga.store import RunStore

    st = RunStore(tmp_path / "r")
    src = _bible([("e1", "Hansje", "boy"), ("e2", "moeder", "mother")], [("e2", "e1", "moeder van")], ["Hansje valt"])
    design = _bible([("e1", "Teun", "boy"), ("e2", "moeder", "mother")], [("e2", "e1", "moeder van")], ["Teun valt"])
    text = _bible([("t1", "de jongen", "a boy"), ("t2", "Moeke", "his mother")], [], ["Teun valt"])
    st.write_json("bible_source.json", src)
    st.write_json("bible.json", design)
    st.write_json("recovered/bible_source.json", text)
    st.write_json("transform.json", {"renames": [{"original": "Hansje", "new": "Teun", "kind": "character"}]})
    st.write_json("recovered/alignment.json", {"pairs": [{"design": "e1", "text": "t1", "method": "model"},
                                                          {"design": "e2", "text": "t2", "method": "model"}],
                                               "checks": {"edge:relation:e2:e1": {"realised": "yes", "evidence": "Moeke riep"}},
                                               "stats": {"rules": 0}})
    g = text_comparison(st, "source")
    node = {n["id"]: n for n in g["nodes"]}
    assert node["e1"]["status"] == "kept" and node["e1"]["details"]["matched_by"] == "model alignment"
    assert [e["status"] for e in g["edges"] if e["type"] == "relation"] == ["kept"]
    assert node["e1"]["label"] == "Hansje"            # in source coordinates: what happened to the original
