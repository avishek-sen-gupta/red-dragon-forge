"""What a FLOWS_TO edge carries, and what it deliberately does not."""

from __future__ import annotations

import pytest
from cobble.corpus_index import CorpusIndex
from cobble.dataflow.fields.emit import field_id, graph_records
from cobble.dataflow.fixpoint.fixpoint import analyse
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
def records_of(program_of, layout_of):
    """One program's nodes, edges and declared extents."""

    def build(statements, data_fields):
        asg = program_of(statements, data_fields=data_fields)
        layout = layout_of(asg)
        return graph_records(analyse(asg, layout.index), layout, CorpusIndex())

    return build


@pytest.fixture
def moved(records_of, two_fields):
    def build():
        return records_of(
            [{"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]}],
            two_fields,
        )

    return build


def _flows(edges):
    return tuple(edge for edge in edges if edge.kind is EdgeKind.FLOWS_TO)


def _owned(records):
    return {field.id: field.extents for field in records.extents}


def test_a_field_id_is_scoped_by_program():
    assert field_id("PROGA", "WS-A") == "PROGA.WS-A"


def test_an_edge_runs_between_two_field_nodes(moved):
    edges = moved().edges
    (edge,) = _flows(edges)
    assert (edge.source, edge.target) == ("PROGA.WS-A", "PROGA.WS-B")
    assert edge.source_kind is NodeKind.FIELD
    assert edge.target_kind is NodeKind.FIELD


def test_the_graph_holds_only_the_endpoints_not_every_declared_field(moved):
    """REC is declared and no value moves through it, so it is not a flow fact.

    Its extents still reach the artefact -- in extents.jsonl, which is where a
    reader intersects a group write against the children it covered."""
    nodes = moved().nodes
    assert {node.id for node in nodes} == {"PROGA.WS-A", "PROGA.WS-B"}
    assert {node.kind for node in nodes} == {NodeKind.FIELD}


def test_a_node_states_why_it_has_no_file_rather_than_never_asking(moved):
    """NOT_ATTEMPTED would claim no index was in reach; one was, and it answered."""
    nodes = moved().nodes
    assert {node.location for node in nodes} == {
        NoFileLocation(FileLocationReason.NOT_INDEXED)
    }


def test_an_edge_carries_both_extents_and_the_cfg_node(moved):
    edges = moved().edges
    (edge,) = _flows(edges)
    assert edge.attrs["node"] == "MAIN/0"
    assert edge.attrs["source_extent"].endswith("[0:4]")
    assert edge.attrs["target_extent"].endswith("[4:8]")


def test_where_a_moved_value_came_from_is_a_row_of_its_own_not_an_attribute(
    records_of, two_fields
):
    """``node`` moved the value; the defs table says where the value came from.

    Pinned on the edge it multiplied it: one source range at one node commonly
    has several reaching definitions, and each one became a whole edge restating
    the identical flow. Here the INITIALIZE covers WS-A and the MOVE carries it
    on, so the row keyed by the MOVE and WS-A's range names the INITIALIZE."""
    records = records_of(
        [
            {"type": "INITIALIZE", "operands": ["REC"]},
            {"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-B"}]},
        ],
        two_fields,
    )
    (moved_on,) = tuple(
        edge for edge in _flows(records.edges) if edge.source == "PROGA.WS-A"
    )
    assert moved_on.attrs["node"] == "MAIN/1"
    assert "source_node" not in moved_on.attrs
    assert {(entry.node, entry.extent): entry.definers for entry in records.defs} == {
        ("MAIN/1", "WS-A@working_storage[0:4]"): ("MAIN/0",)
    }


def test_a_field_publishes_how_it_was_declared_and_not_only_where(moved):
    """Level and usage: the two facts ranges alone cannot recover.

    A group owning exactly its one child's bytes is indistinguishable from that
    child by range, so containment needs the level. And a partial overlap of a
    COMP field is not a partial read of its value, so a consumer intersecting
    intervals needs the usage before it interprets the overlap."""
    declared = {field.id: (field.level, field.usage) for field in moved().extents}
    assert declared["PROGA.REC"][0] == 1
    assert declared["PROGA.WS-B"] == (5, "DISPLAY")


def test_an_edge_does_not_carry_a_guard_condition(moved):
    """Conditions stay out of the lattice; a reader asks srccfg for the node's."""
    edges = moved().edges
    (edge,) = _flows(edges)
    assert "condition" not in edge.attrs
    assert "guard" not in edge.attrs


def test_an_edge_does_not_name_the_other_fields_its_extents_touch(moved):
    """That is a layout question, and extents.jsonl answers it once per field.

    Repeating it per edge cost most of the artefact -- a record's REDEFINES views
    restated on every flow through them -- to say what the layout says already."""
    edges = moved().edges
    assert "target_fields" not in _flows(edges)[0].attrs
    assert "source_fields" not in _flows(edges)[0].attrs


def test_a_node_carries_no_extents_of_its_own(moved):
    """Identity and location only. Geometry is a separate artefact."""
    assert {tuple(node.attrs) for node in moved().nodes} == {()}


def test_every_declared_field_publishes_the_bytes_its_name_owns(moved):
    """Declared, including REC, which no edge names -- that is the point of it."""
    assert _owned(moved()) == {
        "PROGA.REC": ("REC@working_storage[0:8]",),
        "PROGA.WS-A": ("WS-A@working_storage[0:4]",),
        "PROGA.WS-B": ("WS-B@working_storage[4:8]",),
    }


def test_a_redefines_view_and_the_field_it_covers_own_the_same_bytes(records_of, field):
    """Which is how a consumer finds the alias: two entries, one byte range.

    Aliasing used to be an edge attribute naming every view of the moved extent.
    Here it is stated once, and stated for views no edge ever moved through."""
    records = records_of(
        [{"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-ALT"}]}],
        [
            field(1, "REC-A", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)]),
            field(
                1,
                "REC-B",
                offset=0,
                redefines="REC-A",
                children=[field(5, "WS-ALT", "X(4)", offset=0)],
            ),
        ],
    )
    owned = _owned(records)
    assert owned["PROGA.WS-A"] == ("WS-A@working_storage[0:4]",)
    assert owned["PROGA.WS-ALT"] == ("WS-ALT@working_storage[0:4]",)


def test_an_occurs_element_owns_one_range_per_occurrence_not_one_span(
    records_of, field
):
    """A span from the first occurrence to the last would swallow the siblings.

    WS-T and WS-U alternate down the table, so ``WS-T[0:12]`` would claim every
    byte of WS-U as well -- and a write to one would report as covering both."""
    records = records_of(
        [{"type": "MOVE", "operands": [{"name": "WS-A"}, {"name": "WS-T"}]}],
        [
            field(1, "REC-A", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)]),
            field(
                1,
                "REC-T",
                offset=4,
                children=[
                    field(
                        5,
                        "TAB-ENTRY",
                        offset=0,
                        occurs=2,
                        children=[
                            field(10, "WS-T", "X(4)", offset=0),
                            field(10, "WS-U", "X(4)", offset=4),
                        ],
                    )
                ],
            ),
        ],
    )
    assert _owned(records)["PROGA.WS-T"] == (
        "WS-T@working_storage[4:8]",
        "WS-T@working_storage[12:16]",
    )


def test_a_group_initialize_is_one_edge_at_the_group_not_one_per_child(
    records_of, two_fields
):
    """Both children were written, both from LITERAL, both by this statement.

    So the per-child edges said one thing twice, differing only in a target
    extent REC's own extent contains -- and REC, WS-A and WS-B all publish
    their extents, so a reader intersects and gets the children back. This was
    most of the rows on a corpus member."""
    records = records_of([{"type": "INITIALIZE", "operands": ["REC"]}], two_fields)
    (edge,) = _flows(records.edges)
    assert (edge.source, edge.target) == ("PROGA.LITERAL", "PROGA.REC")
    assert edge.attrs["target_extent"] == "REC@working_storage[0:8]"


def test_a_synthetic_origin_becomes_its_own_field_node(records_of, field):
    """A value from outside storage has an origin where an extent would be."""
    records = records_of(
        [{"type": "INITIALIZE", "operands": ["REC"]}],
        [field(1, "REC", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    (edge,) = _flows(records.edges)
    assert edge.source == "PROGA.LITERAL"
    assert edge.attrs["source_extent"] == ""


def test_a_synthetic_origin_has_no_entry_rather_than_an_empty_range(records_of, field):
    """It is a node in the graph and it is not storage, so it declares nothing.

    An absent entry is what a consumer intersecting intervals needs: a
    zero-length range at offset zero is still a range, and a test that counts
    touching at a boundary would match it against the first field of working
    storage."""
    records = records_of(
        [{"type": "INITIALIZE", "operands": ["REC"]}],
        [field(1, "REC", offset=0, children=[field(5, "WS-A", "X(4)", offset=0)])],
    )
    assert "PROGA.LITERAL" in {node.id for node in records.nodes}
    assert "PROGA.LITERAL" not in _owned(records)
