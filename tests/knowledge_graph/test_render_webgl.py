"""render_webgl_html(): the WebGL stakeholder view of a whole corpus graph.

The properties under test are the ones that make a corpus-sized graph viewable
at all -- coordinates baked in rather than simulated, no per-edge label, edges
carrying indices rather than repeated node ids -- plus the one that makes the
file safe to hand to somebody: node attrs, which carry raw in-stream JCL text,
are not in it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

import networkx as nx
import pytest

from cobble.file_location import NOT_ATTEMPTED
from cobble.interpreter.project.graph_types import AttrValue, EdgeKind, NodeKind
from cobble.knowledge_graph import render_webgl as render_webgl_module
from cobble.knowledge_graph.node_key import NodeKey
from cobble.knowledge_graph.render_webgl import render_webgl_html

_NO_ATTRS: Mapping[str, AttrValue] = {}


def _node(
    graph: nx.MultiDiGraph,
    kind: NodeKind,
    node_id: str,
    attrs: Mapping[str, AttrValue] = _NO_ATTRS,
) -> NodeKey:
    key = (kind, node_id)
    graph.add_node(
        key, kind=kind, id=node_id, location=NOT_ATTEMPTED, attrs=dict(attrs)
    )
    return key


def _sample_graph() -> nx.MultiDiGraph:
    """One program copying two copybooks: a degree-2 hub and two leaves."""
    graph = nx.MultiDiGraph()
    program = _node(graph, NodeKind.PROGRAM, "PROGONE")
    first = _node(graph, NodeKind.COPYBOOK, "COPYONE")
    second = _node(graph, NodeKind.COPYBOOK, "COPYTWO")
    graph.add_edge(program, first, kind=EdgeKind.COPY, attrs={})
    graph.add_edge(program, second, kind=EdgeKind.COPY, attrs={})
    return graph


def _positions(graph: nx.MultiDiGraph) -> Mapping[NodeKey, tuple[float, float]]:
    return {key: (float(n), float(n) * 2) for n, key in enumerate(graph.nodes)}


def _render(tmp_path: Path, graph: nx.MultiDiGraph) -> str:
    output_path = tmp_path / "graph-webgl.html"
    render_webgl_html(graph, _positions(graph), output_path, title="Test Graph")
    return output_path.read_text()


def _json_array(html: str, name: str) -> list:
    """The value of one `const <name> = [...];` line of the generated page."""
    match = re.search(rf"^const {name} = (\[.*\]);$", html, re.M)
    assert match, f"no {name} array in the page"
    return json.loads(match.group(1))


# ── The file itself ───────────────────────────────────────────────


def test_the_page_is_self_contained(tmp_path: Path) -> None:
    """No CDN, no server: both vendored libraries are inlined, so the file can
    be emailed and opened offline."""
    html = _render(tmp_path, _sample_graph())

    assert "<title>Test Graph</title>" in html
    assert "graphology" in html
    assert "Sigma" in html


@pytest.mark.parametrize("missing", ["_SIGMA_JS_PATH", "_GRAPHOLOGY_JS_PATH"])
def test_a_missing_vendored_library_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """Rather than writing a page that silently renders nothing."""
    monkeypatch.setattr(render_webgl_module, missing, tmp_path / "does-not-exist.js")

    with pytest.raises(FileNotFoundError):
        _render(tmp_path, _sample_graph())


def test_the_counts_are_stated_on_the_page(tmp_path: Path) -> None:
    """A stakeholder view has to say how big the thing they are looking at is."""
    html = _render(tmp_path, _sample_graph())

    assert "3 nodes" in html
    assert "2 edges" in html


# ── What makes it fast ────────────────────────────────────────────


def test_each_node_carries_its_precomputed_position(tmp_path: Path) -> None:
    """The whole point of the target: coordinates arrive finished, so nothing
    is simulated in the browser."""
    graph = _sample_graph()
    html = _render(tmp_path, graph)

    rows = _json_array(html, "NODES")
    points = {(row[2], row[3]) for row in rows}
    assert points == set(_positions(graph).values())


def test_a_node_with_no_position_is_refused(tmp_path: Path) -> None:
    """Defaulting to the origin would stack nodes on one another and look like
    a layout bug rather than a wiring bug."""
    graph = _sample_graph()
    incomplete = dict(list(_positions(graph).items())[:-1])

    with pytest.raises(KeyError):
        render_webgl_html(graph, incomplete, tmp_path / "graph-webgl.html")


def test_an_edge_carries_no_label(tmp_path: Path) -> None:
    """113k rendered edge labels is what made the vis-network page unusable at
    corpus scale, and the edge's colour already says its kind."""
    html = _render(tmp_path, _sample_graph())

    rows = _json_array(html, "EDGES")
    assert all(len(row) == 3 for row in rows)
    assert "COPY" not in {field for row in rows for field in row}


def test_an_edge_names_its_endpoints_by_index(tmp_path: Path) -> None:
    """Repeating a node's id in every edge that touches it is most of the
    payload at corpus scale; an index into NODES is a small integer."""
    html = _render(tmp_path, _sample_graph())

    node_count = len(_json_array(html, "NODES"))
    rows = _json_array(html, "EDGES")
    assert all(isinstance(row[0], int) and isinstance(row[1], int) for row in rows)
    assert all(0 <= row[0] < node_count and 0 <= row[1] < node_count for row in rows)


def test_kinds_are_named_once_and_referenced_by_index(tmp_path: Path) -> None:
    html = _render(tmp_path, _sample_graph())

    node_kinds = _json_array(html, "NODE_KINDS")
    assert sorted(node_kinds) == ["COPYBOOK", "PROGRAM"]
    assert {row[1] for row in _json_array(html, "NODES")} <= set(range(len(node_kinds)))
    assert _json_array(html, "EDGE_KINDS") == ["COPY"]


def test_edges_are_drawn_with_arrowheads(tmp_path: Path) -> None:
    """The graph is directed and the direction is the information: CALL and
    COPY read backwards without a head. sigma's arrow program is about twice
    the geometry per edge of its line program, which is the price."""
    html = _render(tmp_path, _sample_graph())

    assert 'defaultEdgeType: "arrow"' in html


def test_the_arrowheads_are_enlarged_past_sigma_defaults(tmp_path: Path) -> None:
    """sigma's stock ratios (2.5 length, 2 wideness) off a 1.7 minimum
    thickness give a head about 4px long, which is invisible with the whole
    corpus on screen. The head is enlarged rather than the edge thickened, so
    the extra ink is on the end that carries the direction, not on 113k edge
    bodies."""
    html = _render(tmp_path, _sample_graph())

    assert "createEdgeArrowProgram" in html
    length = float(re.search(r"lengthToThicknessRatio: ([0-9.]+)", html).group(1))
    wideness = float(re.search(r"widenessToThicknessRatio: ([0-9.]+)", html).group(1))
    assert length > 2.5
    assert wideness > 2


def test_the_page_redraws_once_the_camera_settles(tmp_path: Path) -> None:
    """hideEdgesOnMove skips edges for any frame the camera is moving, and
    sigma's own recovery is a refresh scheduled at setTimeout(0) on mouseup --
    which runs while the 200ms inertia animation is still going, so that frame
    is skipped too and nothing renders again once it ends. Result: edges stay
    hidden after a pan. The page has to redraw once the camera is quiet."""
    html = _render(tmp_path, _sample_graph())

    assert 'getCamera().on("updated"' in html
    assert "isAnimated()" in html
    # A redraw, not a reindex: the graph's structure never changes here.
    assert html.count("skipIndexation: true") >= 3


def test_a_hub_is_drawn_larger_than_a_leaf(tmp_path: Path) -> None:
    """Sizing by degree is what makes the shape of the corpus legible when the
    whole graph is on screen and no label is."""
    html = _render(tmp_path, _sample_graph())

    rows = _json_array(html, "NODES")
    by_label = {row[0]: row[4] for row in rows}
    assert by_label["PROGONE"] > by_label["COPYONE"]


# ── What it deliberately leaves out ───────────────────────────────


def test_node_attrs_never_reach_the_page(tmp_path: Path) -> None:
    """attrs carry verbatim in-stream JCL (see jcl_graph's attrs["text"]) --
    corpus source has no business in a file that gets shown around, and it is
    also where most of the vis-network page's 27MB went."""
    graph = nx.MultiDiGraph()
    _node(
        graph,
        NodeKind.INSTREAM_DATA,
        "JOBONE.STEPONE.SYSIN",
        {"text": "DELETE SOMETHING.SECRET"},
    )
    html = _render(tmp_path, graph)

    assert "SECRET" not in html
    assert "JOBONE.STEPONE.SYSIN" in html
