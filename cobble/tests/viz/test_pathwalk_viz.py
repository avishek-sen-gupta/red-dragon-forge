from __future__ import annotations

import io
import json

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
    node_paragraph_of,
    render_html,
)
from cobble.viz.pathwalk_viz import _edge_kind_lookup as edge_kind_lookup
from cobble.viz.pathwalk_viz import _parser as pathwalk_parser
from cobble.viz.pathwalk_viz import _paths_edges as paths_edges
from cobble.viz.pathwalk_viz import _paths_nodes as paths_nodes

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
        _node("MAIN#label", "MAIN", NodeKind.LABEL),
        _node("MAIN/0", "MAIN"),
        _node("SUB#label", "SUB", NodeKind.LABEL),
        _node("SUB/0", "SUB"),
    ),
    edges=(
        _edge("MAIN/0", "SUB#label", EdgeKind.PERFORM),
        _edge("SUB/0", "MAIN/0", EdgeKind.RETURN),
    ),
)

_NODE_PARA = {
    "MAIN#label": "PROG/MAIN",
    "MAIN/0": "PROG/MAIN",
    "SUB#label": "PROG/SUB",
    "SUB/0": "PROG/SUB",
}

# ---------------------------------------------------------------------------
# collapse_path
# ---------------------------------------------------------------------------


def test_collapse_path_maps_to_paragraphs() -> None:
    path = ("MAIN#label", "MAIN/0", "SUB#label", "SUB/0")
    result = collapse_path(path, _NODE_PARA)
    assert result == ("PROG/MAIN", "PROG/SUB")


def test_collapse_path_removes_consecutive_duplicates() -> None:
    path = ("MAIN#label", "MAIN/0", "MAIN/1")
    node_para = {**_NODE_PARA, "MAIN/1": "PROG/MAIN"}
    result = collapse_path(path, node_para)
    assert result == ("PROG/MAIN",)


def test_collapse_path_empty() -> None:
    assert collapse_path((), _NODE_PARA) == ()


def test_collapse_path_single_node() -> None:
    assert collapse_path(("MAIN/0",), _NODE_PARA) == ("PROG/MAIN",)


def test_collapse_path_qualifies_by_program() -> None:
    """Cross-program name collision: same bare paragraph name, different
    programs, must collapse to distinct qualified keys."""
    node_para_a = {"0000-MAIN/0": "PROGA/0000-MAIN"}
    node_para_b = {"0000-MAIN/0": "PROGB/0000-MAIN"}
    result_a = collapse_path(("0000-MAIN/0",), node_para_a)
    result_b = collapse_path(("0000-MAIN/0",), node_para_b)
    assert result_a == ("PROGA/0000-MAIN",)
    assert result_b == ("PROGB/0000-MAIN",)
    assert result_a != result_b


def test_collapse_path_drops_unknown_node_ids() -> None:
    """A trace-path may visit a node outside the loaded CFG bundle (e.g. a
    callee not included in --cfg). Such ids are dropped rather than
    injected as unresolved placeholders, so the animation stays contiguous."""
    path = ("MAIN#label", "UNKNOWN/99", "MAIN/0")
    result = collapse_path(path, _NODE_PARA)
    assert result == ("PROG/MAIN",)


def test_node_paragraph_of_maps_real_shaped_ids() -> None:
    """node_paragraph_of resolves every node.id to its qualified paragraph
    key via structured fields, covering '#label', '#end', and '/index'
    shapes uniformly."""
    mapping = node_paragraph_of((_CFG,))
    assert mapping["MAIN#label"] == "PROG/MAIN"
    assert mapping["MAIN/0"] == "PROG/MAIN"
    assert mapping["SUB#label"] == "PROG/SUB"
    assert mapping["SUB/0"] == "PROG/SUB"


# ---------------------------------------------------------------------------
# _edge_kind_lookup
# ---------------------------------------------------------------------------


def test_edge_kind_lookup_resolves_perform_and_return() -> None:
    lookup = edge_kind_lookup((_CFG,), _NODE_PARA)
    assert lookup[("PROG/MAIN", "PROG/SUB")] == "PERFORM"
    assert lookup[("PROG/SUB", "PROG/MAIN")] == "RETURN"


def test_edge_kind_lookup_captures_label_and_end_suffixed_edges() -> None:
    """Regression: real cross-paragraph edges route through '#label'/'#end'
    suffixed node ids that contain zero '/' characters -- a PERFORM target
    is always a '#label' node; a RETURN source is always inside the
    performed paragraph. Resolved via node.paragraph, not by splitting the
    id, so both endpoints -- one with no '/' at all -- still resolve."""
    lookup = edge_kind_lookup((_CFG,), _NODE_PARA)
    assert ("PROG/MAIN", "PROG/SUB") in lookup
    assert ("PROG/SUB", "PROG/MAIN") in lookup


def test_edge_kind_lookup_omits_intra_paragraph_edges() -> None:
    cfg = Cfg(
        program="P",
        nodes=(_node("A/0", "A"), _node("A/1", "A")),
        edges=(_edge("A/0", "A/1"),),
    )
    node_para = {"A/0": "P/A", "A/1": "P/A"}
    lookup = edge_kind_lookup((cfg,), node_para)
    assert lookup == {}


# ---------------------------------------------------------------------------
# _paths_nodes / _paths_edges -- derived purely from sampled paths
# ---------------------------------------------------------------------------


def test_paths_nodes_first_seen_order() -> None:
    assert paths_nodes([("A", "B"), ("B", "C")]) == ("A", "B", "C")


def test_paths_nodes_dedupes_across_paths() -> None:
    assert paths_nodes([("A", "B"), ("A", "C")]) == ("A", "B", "C")


def test_paths_nodes_empty() -> None:
    assert paths_nodes([]) == ()


def test_paths_edges_first_seen_order_and_dedup() -> None:
    result = paths_edges([("A", "B", "C"), ("A", "B", "D")])
    assert result == (("A", "B"), ("B", "C"), ("B", "D"))


def test_paths_edges_drops_self_loops() -> None:
    """A path may revisit the same paragraph consecutively (a trivial
    self-loop at paragraph granularity); this is not a drawable edge."""
    assert paths_edges([("A", "A", "B")]) == (("A", "B"),)


def test_paths_edges_empty() -> None:
    assert paths_edges([]) == ()


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
            "nodes": ["MAIN#label", "SUB/0"],
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
            "nodes": ["MAIN#label", "SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    assert bundle["paths"][0]["paragraphs"] == ["PROG/MAIN", "PROG/SUB"]


def test_build_bundle_branch_edges_new_is_list() -> None:
    p0 = {
        "kind": "path",
        "path_index": 0,
        "nodes": ["MAIN#label", "MAIN/0", "SUB#label"],
        "deps": [],
    }
    p1 = {
        "kind": "path",
        "path_index": 1,
        "nodes": ["MAIN#label", "SUB#label"],
        "deps": [],
    }
    bundle = build_bundle((_CFG,), _make_path_jsonl(p0, p1), [], 50, 600)
    assert isinstance(bundle["paths"][0]["branch_edges_new"], list)
    assert isinstance(bundle["paths"][1]["branch_edges_new"], list)


def test_build_bundle_branch_edges_not_repeated_across_paths() -> None:
    # Path 0 covers MAIN->SUB. Path 1 covers the same route.
    p0 = {
        "kind": "path",
        "path_index": 0,
        "nodes": ["MAIN#label", "MAIN/0", "SUB#label"],
        "deps": [],
    }
    p1 = {
        "kind": "path",
        "path_index": 1,
        "nodes": ["MAIN#label", "MAIN/0", "SUB#label"],
        "deps": [],
    }
    bundle = build_bundle((_CFG,), _make_path_jsonl(p0, p1), [], 50, 600)
    # Path 1 sees the same edge MAIN->SUB; it was already covered by path 0
    assert bundle["paths"][1]["branch_edges_new"] == []


def test_build_bundle_vars_in_output() -> None:
    path_jsonl = _make_path_jsonl(
        {"kind": "path", "path_index": 0, "nodes": ["MAIN/0"], "deps": []}
    )
    bundle = build_bundle((_CFG,), path_jsonl, ["FIELD-X", "FIELD-Y"], 100, 300)
    assert bundle["vars"] == ["FIELD-X", "FIELD-Y"]


def test_build_bundle_ignores_non_path_lines() -> None:
    jsonl = io.StringIO(
        json.dumps({"kind": "meta", "info": "ignored"})
        + "\n"
        + json.dumps({"kind": "path", "path_index": 0, "nodes": ["MAIN/0"], "deps": []})
        + "\n"
    )
    bundle = build_bundle((_CFG,), jsonl, [], 50, 600)
    assert len(bundle["paths"]) == 1


def test_build_bundle_nodes_list_has_expected_shape() -> None:
    path_jsonl = _make_path_jsonl(
        {"kind": "path", "path_index": 0, "nodes": ["MAIN/0"], "deps": []}
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    for node in bundle["nodes"]:
        assert "id" in node
        assert "label" in node


def test_build_bundle_edges_list_has_expected_shape() -> None:
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["MAIN/0", "SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    for edge in bundle["edges"]:
        assert "source" in edge
        assert "target" in edge
        assert "kind" in edge


def test_build_bundle_edge_kind_resolved_from_cfg() -> None:
    """The edge a path actually took is labelled with its real kind, looked
    up from the CFG -- not left as a generic default."""
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["MAIN/0", "SUB/0"],
            "deps": [],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    edge = next(
        e
        for e in bundle["edges"]
        if e["source"] == "PROG/MAIN" and e["target"] == "PROG/SUB"
    )
    assert edge["kind"] == "PERFORM"


def test_build_bundle_only_visited_paragraphs_appear() -> None:
    """A paragraph the sampled paths never visited (here: nothing visits
    SUB) contributes no node -- only what --record-paths actually recorded
    is ever drawn."""
    path_jsonl = _make_path_jsonl(
        {"kind": "path", "path_index": 0, "nodes": ["MAIN/0"], "deps": []}
    )
    bundle = build_bundle((_CFG,), path_jsonl, [], 50, 600)
    node_ids = {n["id"] for n in bundle["nodes"]}
    assert node_ids == {"PROG/MAIN"}


def test_build_bundle_scalar_dep_does_not_raise() -> None:
    """Non-Mapping dep element (e.g. a string scalar) must not raise."""
    path_jsonl = _make_path_jsonl(
        {
            "kind": "path",
            "path_index": 0,
            "nodes": ["MAIN/0"],
            "deps": ["not-a-dict", 42, {"target": {"field": "X"}, "source": {}}],
        }
    )
    bundle = build_bundle((_CFG,), path_jsonl, ["X"], 50, 600)
    assert len(bundle["paths"]) == 1


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

_BUNDLE: AnimBundle = {
    "nodes": [
        {"id": "MAIN", "label": "MAIN"},
        {"id": "SUB", "label": "SUB"},
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


def test_render_html_loads_d3_from_cdn(tmp_path):
    """No self-containment requirement here -- the layout is a genuine
    force simulation via d3-force, loaded from a CDN at view time."""
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "d3js.org" in content


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
