"""What a FLOWS_TO edge carries, and what it deliberately does not."""

from __future__ import annotations

import pytest
from cobble.corpus_index import CorpusIndex
from cobble.dataflow.fields.emit import field_id, graph_records
from cobble.dataflow.fields.fixpoint import analyse
from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind


@pytest.fixture
def two_fields(field):
    return [
        field(
            1,
            "REC",
            offset=0,
            children=[
                field(5, "WS-A", "X(4)", offset=0),
                field(5, "WS-B", "X(4)", offset=4),
            ],
        )
    ]


@pytest.fixture
def records_of(program_of, index_of):
    """Nodes and edges for a program, plus the index they were named from."""

    def build(statements, data_fields, expand=False):
        asg = program_of(statements, data_fields=data_fields)
        index = index_of(asg)
        return graph_records(analyse(asg, index), index, expand, CorpusIndex())

    return build


@pytest.fixture
def moved(records_of, two_fields):
    def build(expand=False):
        return records_of(
            [{"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}],
            two_fields,
            expand=expand,
        )

    return build


def _flows(edges):
    return tuple(edge for edge in edges if edge.kind is EdgeKind.FLOWS_TO)


def test_a_field_id_is_scoped_by_program():
    assert field_id("PROGA", "WS-A") == "PROGA.WS-A"


def test_an_edge_runs_between_two_field_nodes(moved):
    _, edges = moved()
    (edge,) = _flows(edges)
    assert (edge.source, edge.target) == ("PROGA.WS-A", "PROGA.WS-B")
    assert edge.source_kind is NodeKind.FIELD
    assert edge.target_kind is NodeKind.FIELD


def test_every_endpoint_appears_as_a_node(moved):
    nodes, _ = moved()
    assert {node.id for node in nodes} == {"PROGA.WS-A", "PROGA.WS-B"}
    assert {node.kind for node in nodes} == {NodeKind.FIELD}


def test_a_node_states_why_it_has_no_file_rather_than_never_asking(moved):
    """NOT_ATTEMPTED would claim no index was in reach; one was, and it answered."""
    nodes, _ = moved()
    assert {node.location for node in nodes} == {
        NoFileLocation(FileLocationReason.NOT_INDEXED)
    }


def test_an_edge_carries_both_extents_and_the_cfg_node(moved):
    _, edges = moved()
    (edge,) = _flows(edges)
    assert edge.attrs["node"] == "MAIN/0"
    assert edge.attrs["source_extent"].endswith("[0:4]")
    assert edge.attrs["target_extent"].endswith("[4:8]")


def test_an_edge_names_the_statement_that_defined_its_source(records_of, two_fields):
    """``node`` moved the value; ``source_node`` is where the value came from.

    Without the second, an edge can only say which statement moved the bytes --
    so a child field filled by a group-level write reports the mover and nothing
    about the group write, which is the case a reader is asking about. Here the
    INITIALIZE covers WS-A and the MOVE carries it on, and only source_node
    distinguishes them."""
    _, edges = records_of(
        [
            {"type": "INITIALIZE", "operands": ["REC"]},
            {"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]},
        ],
        two_fields,
    )
    (moved_on,) = tuple(edge for edge in _flows(edges) if edge.source == "PROGA.WS-A")

    assert (moved_on.attrs["node"], moved_on.attrs["source_node"]) == (
        "MAIN/1",
        "MAIN/0",
    )


def test_an_edge_does_not_carry_a_guard_condition(moved):
    """Conditions stay out of the lattice; a reader asks srccfg for the node's."""
    _, edges = moved()
    (edge,) = _flows(edges)
    assert "condition" not in edge.attrs
    assert "guard" not in edge.attrs


def test_extents_are_absent_from_attrs_until_expansion_is_asked_for(moved):
    """Expansion is one attribute per aliasing view, so it is opt-in."""
    _, plain = moved()
    _, expanded = moved(expand=True)
    assert "target_fields" not in _flows(plain)[0].attrs
    assert _flows(expanded)[0].attrs["target_fields"] == "WS-B,REC"


def test_expansion_names_every_field_the_source_extent_touches(moved):
    _, edges = moved(expand=True)
    assert _flows(edges)[0].attrs["source_fields"] == "WS-A,REC"


def test_a_synthetic_origin_becomes_its_own_field_node(records_of, field):
    """A value from outside storage has an origin where an extent would be."""
    _, edges = records_of(
        [{"type": "INITIALIZE", "operands": ["REC"]}],
        [field(1, "REC", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    (edge,) = _flows(edges)
    assert edge.source == "PROGA.LITERAL"
    assert edge.attrs["source_extent"] == ""


def test_a_synthetic_origin_is_not_expanded_to_a_covering_field(records_of, field):
    """NOWHERE overlaps nothing, and naming it after a field would be a lie."""
    _, edges = records_of(
        [{"type": "INITIALIZE", "operands": ["REC"]}],
        [field(1, "REC", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)])],
        expand=True,
    )
    assert _flows(edges)[0].attrs["source_fields"] == ""
