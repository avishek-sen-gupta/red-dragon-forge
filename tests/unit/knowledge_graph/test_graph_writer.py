# pyright: standard
import json
from pathlib import Path

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from knowledge_graph.graph_writer import GraphWriter


def _read(p: Path):
    return [json.loads(line) for line in p.read_text().splitlines()]


def test_edges_dedupe_keep_first(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    e = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.PROGRAM, kind=EdgeKind.XCTL, attrs={"first": 1})
    e2 = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                   target_kind=NodeKind.PROGRAM, kind=EdgeKind.XCTL, attrs={"second": 2})
    with GraphWriter(np_, ep) as w:
        w.add_edge(e)
        w.add_edge(e2)
    rows = _read(ep)
    assert len(rows) == 1 and rows[0]["attrs"] == {"first": 1}  # keep-first


def test_node_merge_bare_endpoint_then_real(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    bare = GraphNode(id="P", kind=NodeKind.PROGRAM)                       # file_path=None
    real = GraphNode(id="P", kind=NodeKind.PROGRAM, file_path="x.cbl",
                     attrs={"loc": 9})
    with GraphWriter(np_, ep) as w:
        w.add_node(bare)
        w.add_node(real)      # bare first, real second
    rows = _read(np_)
    assert len(rows) == 1
    assert rows[0]["file_path"] == "x.cbl"      # non-None wins regardless of order
    assert rows[0]["attrs"] == {"loc": 9}       # attr union


def test_add_edge_synthesizes_bare_endpoints(tmp_path):
    # Endpoints NEVER explicitly add_node'd — merge_graph creates bare nodes for
    # them; GraphWriter must do the same or a diligent-extractor-free edge would
    # silently drop nodes.
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    e = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.COPYBOOK, kind=EdgeKind.COPY)
    with GraphWriter(np_, ep) as w:
        w.add_edge(e)
    rows = {(r["id"], r["kind"]): r for r in _read(np_)}
    assert len(rows) == 2
    assert rows[("A", "PROGRAM")]["file_path"] is None
    assert rows[("A", "PROGRAM")]["attrs"] == {}
    assert rows[("B", "COPYBOOK")]["file_path"] is None
    assert rows[("B", "COPYBOOK")]["attrs"] == {}


def test_synthesized_endpoint_then_real_node_merges(tmp_path):
    # A bare endpoint synthesized by add_edge, then a later explicit add_node with
    # file_path+attrs for the same (kind,id), must merge (non-None wins, attr
    # union) — order-independent vs. the explicit call coming first.
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    e = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.PROGRAM, kind=EdgeKind.CALL)
    real_a = GraphNode(id="A", kind=NodeKind.PROGRAM, file_path="a.cbl",
                       attrs={"loc": 5})
    with GraphWriter(np_, ep) as w:
        w.add_edge(e)        # synthesizes bare A + bare B
        w.add_node(real_a)   # upgrades A
    rows = {(r["id"], r["kind"]): r for r in _read(np_)}
    assert rows[("A", "PROGRAM")]["file_path"] == "a.cbl"
    assert rows[("A", "PROGRAM")]["attrs"] == {"loc": 5}
    assert rows[("B", "PROGRAM")]["file_path"] is None  # untouched endpoint stays bare


def test_real_node_then_synthesized_endpoint_merges(tmp_path):
    # Reverse order: explicit real node first, then add_edge whose endpoint reuses
    # the same (kind,id). The bare synthesis must NOT clobber the real node.
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    real_a = GraphNode(id="A", kind=NodeKind.PROGRAM, file_path="a.cbl",
                       attrs={"loc": 5})
    e = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.PROGRAM, kind=EdgeKind.CALL)
    with GraphWriter(np_, ep) as w:
        w.add_node(real_a)   # real A first
        w.add_edge(e)        # bare-synthesis of A must not clobber
    rows = {(r["id"], r["kind"]): r for r in _read(np_)}
    assert rows[("A", "PROGRAM")]["file_path"] == "a.cbl"
    assert rows[("A", "PROGRAM")]["attrs"] == {"loc": 5}


def test_partial_write_atomic(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    w = GraphWriter(np_, ep)
    w.add_node(GraphNode(id="P", kind=NodeKind.PROGRAM))
    assert not np_.exists()                     # nothing on disk until close()
    w.close()
    assert np_.exists()
