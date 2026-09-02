"""sfdp_positions(): graph -> one (x, y) per node, computed once by graphviz.

Precomputing the layout is what lets the WebGL page open already laid out
instead of running a force simulation in the browser -- so these tests pin
that every node gets a position, including one no edge touches, and that a
missing graphviz says so plainly rather than producing a page with every node
stacked at the origin.
"""

from __future__ import annotations

import shutil

import networkx as nx
import pytest

from cobble.file_location import NOT_ATTEMPTED
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind
from cobble.knowledge_graph import layout as layout_module
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.node_key import NodeKey

needs_graphviz = pytest.mark.skipif(
    not shutil.which("sfdp"), reason="graphviz's sfdp is not installed"
)


def _node(graph: nx.MultiDiGraph, kind: NodeKind, node_id: str) -> NodeKey:
    key = (kind, node_id)
    graph.add_node(key, kind=kind, id=node_id, location=NOT_ATTEMPTED, attrs={})
    return key


def _sample_graph() -> nx.MultiDiGraph:
    """Two connected nodes plus one nothing points at."""
    graph = nx.MultiDiGraph()
    program = _node(graph, NodeKind.PROGRAM, "PROGONE")
    copybook = _node(graph, NodeKind.COPYBOOK, "COPYONE")
    _node(graph, NodeKind.DATASET, "TEST.DATA")
    graph.add_edge(program, copybook, kind=EdgeKind.COPY, attrs={})
    return graph


@needs_graphviz
def test_every_node_gets_a_position_including_an_unconnected_one() -> None:
    """An isolated node has to be declared in the DOT, not just implied by an
    edge -- otherwise graphviz never sees it and it renders at (0, 0)."""
    positions = sfdp_positions(_sample_graph())

    assert set(positions) == set(_sample_graph().nodes)
    assert all(len(xy) == 2 for xy in positions.values())


@needs_graphviz
def test_connected_nodes_are_laid_out_apart() -> None:
    """A layout that returned the same point for everything would satisfy the
    test above while being useless."""
    positions = sfdp_positions(_sample_graph())

    assert len(set(positions.values())) == 3


@needs_graphviz
def test_an_empty_graph_needs_no_layout() -> None:
    assert sfdp_positions(nx.MultiDiGraph()) == {}


def test_a_missing_sfdp_is_reported_as_a_missing_sfdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        layout_module, "_SFDP_COMMAND", ("cobble-no-such-layout-engine", "-Tplain")
    )

    with pytest.raises(FileNotFoundError, match="sfdp"):
        sfdp_positions(_sample_graph())


def test_a_failing_sfdp_reports_its_own_complaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A graphviz that runs but rejects the input must not pass for a layout."""
    monkeypatch.setattr(layout_module, "_SFDP_COMMAND", ("sfdp", "-Tnosuchformat"))

    with pytest.raises(RuntimeError, match="sfdp"):
        sfdp_positions(_sample_graph())


def test_only_node_lines_of_the_plain_output_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """-Tplain interleaves graph/node/edge/stop lines, and an edge line carries
    coordinates of its own that are no node's position."""
    plain = "\n".join(
        (
            "graph 1.0 10.0 10.0",
            "node 0 1.5 2.5 0.5 0.5 x solid ellipse black lightgrey",
            "node 1 3.5 4.5 0.5 0.5 x solid ellipse black lightgrey",
            "node 2 5.5 6.5 0.5 0.5 x solid ellipse black lightgrey",
            "edge 0 1 4 9.9 9.9 9.9 9.9 9.9 9.9 9.9 9.9 solid black",
            "stop",
        )
    )
    monkeypatch.setattr(layout_module, "_run_sfdp", lambda _dot: plain)

    positions = sfdp_positions(_sample_graph())

    assert sorted(positions.values()) == [(1.5, 2.5), (3.5, 4.5), (5.5, 6.5)]
