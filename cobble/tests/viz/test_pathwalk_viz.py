from __future__ import annotations

import io
import json

import networkx as nx
from cobble.dataflow.srccfg.cfg import (
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    SourceSpan,
)
from cobble.viz.pathwalk_viz import (
    AnimBundle,
    JsonRecord,
    build_bundle,
    collapse_path,
    layered_positions,
    paragraph_graph,
    paragraphs_of,
    render_html,
)
from cobble.viz.pathwalk_viz import _parser as pathwalk_parser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SPAN = SourceSpan(line_start=1, col_start=1, line_end=1, col_end=10)
_ATOM = Atom(text="")


def _node(id_: str, para: str, kind: NodeKind = NodeKind.ASSIGN) -> Node:
    return Node(id=id_, kind=kind, paragraph=para, atom=_ATOM, span=_SPAN)


def _edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.FLOW) -> Edge:
    return Edge(source=src, target=tgt, kind=kind)


_CFG = Cfg(
    program="PROG",
    nodes=(
        _node("PROG/MAIN/label", "MAIN", NodeKind.LABEL),
        _node("PROG/MAIN/0", "MAIN"),
        _node("PROG/SUB/label", "SUB", NodeKind.LABEL),
        _node("PROG/SUB/0", "SUB"),
    ),
    edges=(
        _edge("PROG/MAIN/0", "PROG/SUB/label", EdgeKind.PERFORM),
        _edge("PROG/SUB/0", "PROG/MAIN/0", EdgeKind.RETURN),
    ),
)

# ---------------------------------------------------------------------------
# collapse_path
# ---------------------------------------------------------------------------


def test_collapse_path_maps_to_paragraphs() -> None:
    path = ("PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label", "PROG/SUB/0")
    result = collapse_path(path)
    assert result == ("PROG/MAIN", "PROG/SUB")


def test_collapse_path_removes_consecutive_duplicates() -> None:
    path = ("PROG/MAIN/label", "PROG/MAIN/0", "PROG/MAIN/1")
    result = collapse_path(path)
    assert result == ("PROG/MAIN",)


def test_collapse_path_empty() -> None:
    assert collapse_path(()) == ()


def test_collapse_path_single_node() -> None:
    assert collapse_path(("PROG/MAIN/0",)) == ("PROG/MAIN",)


def test_collapse_path_qualifies_by_program() -> None:
    """Cross-program name collision: same bare paragraph name, different
    programs, must collapse to distinct qualified keys."""
    path_a = ("PROGA/0000-MAIN/0",)
    path_b = ("PROGB/0000-MAIN/0",)
    result_a = collapse_path(path_a)
    result_b = collapse_path(path_b)
    assert result_a == ("PROGA/0000-MAIN",)
    assert result_b == ("PROGB/0000-MAIN",)
    assert result_a != result_b


# ---------------------------------------------------------------------------
# paragraphs_of
# ---------------------------------------------------------------------------


def test_paragraphs_of_returns_node_ids() -> None:
    mapping = paragraphs_of((_CFG,))
    assert "PROG/MAIN" in mapping
    assert "PROG/SUB" in mapping
    assert "PROG/MAIN/0" in mapping["PROG/MAIN"]
    assert "PROG/MAIN/label" in mapping["PROG/MAIN"]
    assert "PROG/SUB/0" in mapping["PROG/SUB"]


# ---------------------------------------------------------------------------
# paragraph_graph
# ---------------------------------------------------------------------------


def test_paragraph_graph_has_both_paragraphs() -> None:
    g = paragraph_graph((_CFG,))
    assert "PROG/MAIN" in g.nodes
    assert "PROG/SUB" in g.nodes


def test_paragraph_graph_has_perform_edge() -> None:
    g = paragraph_graph((_CFG,))
    # MAIN/0 --PERFORM--> SUB/label: different paragraphs → graph edge
    assert g.has_edge("PROG/MAIN", "PROG/SUB")


def test_paragraph_graph_no_self_loops_for_intra_para_edges() -> None:
    cfg = Cfg(
        program="P",
        nodes=(
            _node("P/A/0", "A"),
            _node("P/A/1", "A"),
        ),
        edges=(_edge("P/A/0", "P/A/1"),),
    )
    g = paragraph_graph((cfg,))
    assert not g.has_edge("P/A", "P/A")


def test_paragraph_graph_qualifies_by_program_on_name_collision() -> None:
    """Finding 1: two programs each declaring a paragraph named the same
    ("0000-MAIN") must NOT collapse into one graph node."""
    cfg_a = Cfg(
        program="PROGA",
        nodes=(_node("PROGA/0000-MAIN/0", "0000-MAIN"),),
        edges=(),
    )
    cfg_b = Cfg(
        program="PROGB",
        nodes=(_node("PROGB/0000-MAIN/0", "0000-MAIN"),),
        edges=(),
    )
    g = paragraph_graph((cfg_a, cfg_b))
    assert "PROGA/0000-MAIN" in g.nodes
    assert "PROGB/0000-MAIN" in g.nodes
    assert g.number_of_nodes() == 2


# ---------------------------------------------------------------------------
# layered_positions
# ---------------------------------------------------------------------------


def test_layered_positions_all_nodes_placed() -> None:
    g = nx.DiGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    positions = layered_positions(g)
    assert set(positions.keys()) == {"A", "B", "C"}


def test_layered_positions_y_increases_with_depth() -> None:
    g = nx.DiGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    pos = layered_positions(g)
    assert pos["A"][1] < pos["B"][1] < pos["C"][1]


def test_layered_positions_values_in_unit_range() -> None:
    g = nx.DiGraph()
    g.add_edge("X", "Y")
    pos = layered_positions(g)
    for x, y in pos.values():
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


def test_layered_positions_single_node() -> None:
    g = nx.DiGraph()
    g.add_node("SOLO")
    pos = layered_positions(g)
    assert "SOLO" in pos


def test_layered_positions_cycle_handled() -> None:
    g = nx.DiGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "A")
    pos = layered_positions(g)
    assert set(pos.keys()) == {"A", "B"}


# ---------------------------------------------------------------------------
# build_bundle — structure
# ---------------------------------------------------------------------------


def _make_path_jsonl(*records: JsonRecord) -> io.StringIO:
    return io.StringIO("\n".join(json.dumps(r) for r in records) + "\n")


def test_build_bundle_has_required_keys() -> None:
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["PROG/MAIN/label", "PROG/SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, ["FIELD-A"], 50, 600)
    assert "nodes" in bundle
    assert "edges" in bundle
    assert "paths" in bundle
    assert "vars" in bundle
    assert bundle["speed_ms"] == 50
    assert bundle["pause_ms"] == 600


def test_build_bundle_path_has_paragraph_list() -> None:
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["PROG/MAIN/label", "PROG/SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    assert bundle["paths"][0]["paragraphs"] == ["PROG/MAIN", "PROG/SUB"]


def test_build_bundle_branch_edges_new_is_list() -> None:
    p0 = {
        "kind": "path",
        "path_index": 0,
        "nodes": ["PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label"],
        "deps": [],
    }
    p1 = {
        "kind": "path",
        "path_index": 1,
        "nodes": ["PROG/MAIN/label", "PROG/SUB/label"],
        "deps": [],
    }
    bundle = build_bundle((_CFG,), _make_path_jsonl(p0, p1), [], 50, 600)
    assert isinstance(bundle["paths"][0]["branch_edges_new"], list)
    assert isinstance(bundle["paths"][1]["branch_edges_new"], list)


def test_build_bundle_branch_edges_not_repeated_across_paths() -> None:
    # Path 0 covers MAIN->SUB (via PERFORM edge). Path 1 covers same route.
    p0 = {
        "kind": "path",
        "path_index": 0,
        "nodes": ["PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label"],
        "deps": [],
    }
    p1 = {
        "kind": "path",
        "path_index": 1,
        "nodes": ["PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label"],
        "deps": [],
    }
    bundle = build_bundle((_CFG,), _make_path_jsonl(p0, p1), [], 50, 600)
    # Path 1 sees the same edge MAIN->SUB; it was already covered by path 0
    assert bundle["paths"][1]["branch_edges_new"] == []


def test_build_bundle_vars_in_output() -> None:
    path_jsonl = _make_path_jsonl(
        {"kind": "path", "path_index": 0, "nodes": ["PROG/MAIN/0"], "deps": []}
    )
    bundle = build_bundle((_CFG,), path_jsonl, ["FIELD-X", "FIELD-Y"], 100, 300)
    assert bundle["vars"] == ["FIELD-X", "FIELD-Y"]


def test_build_bundle_ignores_non_path_lines() -> None:
    jsonl = io.StringIO(
        json.dumps({"kind": "meta", "info": "ignored"})
        + "\n"
        + json.dumps(
            {"kind": "path", "path_index": 0, "nodes": ["PROG/MAIN/0"], "deps": []}
        )
        + "\n"
    )
    bundle = build_bundle((_CFG,), jsonl, [], 50, 600)
    assert len(bundle["paths"]) == 1


def test_build_bundle_nodes_list_has_expected_shape() -> None:
    path_jsonl = _make_path_jsonl(
        {"kind": "path", "path_index": 0, "nodes": ["PROG/MAIN/0"], "deps": []}
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    for node in bundle["nodes"]:
        assert "id" in node
        assert "x" in node
        assert "y" in node
        assert "kind" in node


def test_build_bundle_edges_list_has_expected_shape() -> None:
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["PROG/MAIN/0", "PROG/SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    for edge in bundle["edges"]:
        assert "source" in edge
        assert "target" in edge
        assert "kind" in edge


def test_build_bundle_scalar_dep_does_not_raise() -> None:
    """Finding 1: non-Mapping dep element (e.g. a string scalar) must not raise."""
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["PROG/MAIN/0"],
            "deps": ["not-a-dict", 42, {"target": {"field": "X"}, "source": {}}],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, ["X"], 50, 600)
    assert len(bundle["paths"]) == 1


def test_layered_positions_two_independent_cycles_y_increases() -> None:
    """Finding 2: two independent cycles (A↔B and C↔D with A->C) must be fully
    stripped so topological_generations succeeds and y increases with depth.

    After stripping all back-edges both cycles are removed.  The only surviving
    forward edge is A->C, so A must appear at a shallower depth than C.
    All four nodes must still be present in the output.
    """
    g = nx.DiGraph()
    g.add_edges_from([("A", "B"), ("B", "A"), ("C", "D"), ("D", "C"), ("A", "C")])
    pos = layered_positions(g)
    assert set(pos.keys()) == {"A", "B", "C", "D"}
    # A->C is the only surviving DAG edge: A must be shallower than C.
    assert pos["A"][1] < pos["C"][1]


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

_BUNDLE: AnimBundle = {
    "nodes": [
        {"id": "MAIN", "label": "MAIN", "x": 0.5, "y": 0.1, "kind": "LABEL"},
        {"id": "SUB", "label": "SUB", "x": 0.5, "y": 0.7, "kind": "ASSIGN"},
    ],
    "edges": [{"source": "MAIN", "target": "SUB", "kind": "PERFORM"}],
    "paths": [
        {"paragraphs": ["MAIN", "SUB"], "branch_edges_new": [], "provenance": {}}
    ],
    "vars": [],
    "speed_ms": 50,
    "pause_ms": 600,
}


def test_render_html_produces_file(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    assert out.exists()
    assert out.stat().st_size > 1000


def test_render_html_is_self_contained(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    # The only http:// allowed is the SVG namespace
    import re

    external_urls = [
        u
        for u in re.findall(r'https?://[^\s"]+', content)
        if "w3.org/2000/svg" not in u and "w3.org/1999/xlink" not in u
    ]
    assert external_urls == [], f"External URLs found: {external_urls}"
    assert "cdn" not in content.lower()


def test_render_html_embeds_data(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "const DATA" in content
    assert '"MAIN"' in content


def test_render_html_has_svg_element(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "<svg" in content


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def test_cli_parser_accepts_required_args(tmp_path):
    p = pathwalk_parser()
    args = p.parse_args(
        [
            "--cfg",
            str(tmp_path / "cfg.json"),
            "--paths",
            str(tmp_path / "paths.jsonl"),
            "--vars",
            "FIELD-A,FIELD-B",
            "--output",
            str(tmp_path / "out.html"),
        ]
    )
    assert args.vars == ["FIELD-A", "FIELD-B"]
    assert args.speed == 50
    assert args.pause == 600


def test_cli_parser_speed_override(tmp_path):
    p = pathwalk_parser()
    args = p.parse_args(
        [
            "--cfg",
            str(tmp_path / "cfg.json"),
            "--paths",
            str(tmp_path / "paths.jsonl"),
            "--vars",
            "F",
            "--output",
            str(tmp_path / "out.html"),
            "--speed",
            "200",
        ]
    )
    assert args.speed == 200
