import pytest

from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def test_graph_node_equality_is_by_value() -> None:
    a = GraphNode(
        id="ACCTFILE", kind=NodeKind.PROGRAM, file_path="app/cbl/ACCTFILE.cbl"
    )
    b = GraphNode(
        id="ACCTFILE", kind=NodeKind.PROGRAM, file_path="app/cbl/ACCTFILE.cbl"
    )
    assert a == b


def test_graph_node_defaults() -> None:
    node = GraphNode(id="COACTVW", kind=NodeKind.PROGRAM)
    assert node.file_path is None
    assert node.attrs == {}


def test_graph_node_is_unhashable_due_to_dict_attrs_field() -> None:
    # frozen=True alone doesn't make a dataclass hashable when a field (attrs)
    # is itself an unhashable dict, even when that dict is empty.
    node = GraphNode(id="COACTVW", kind=NodeKind.PROGRAM)
    with pytest.raises(TypeError):
        hash(node)


def test_graph_edge_equality_is_by_value() -> None:
    a = GraphEdge(
        source="COACTVW",
        source_kind=NodeKind.PROGRAM,
        target="COACTVW",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )
    b = GraphEdge(
        source="COACTVW",
        source_kind=NodeKind.PROGRAM,
        target="COACTVW",
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )
    assert a == b


def test_node_kind_values() -> None:
    assert {k.value for k in NodeKind} == {
        "PROGRAM",
        "COPYBOOK",
        "TRANSACTION",
        "JOB",
        "STEP",
        "DATASET",
        "BMS_MAP",
        "CICS_FILE",
        "INSTREAM_DATA",
        "COBOL_FILE",
    }


def test_edge_kind_values() -> None:
    assert {k.value for k in EdgeKind} == {
        "CALL",
        "COPY",
        "XCTL",
        "LINK",
        "RETURN_TRANSID",
        "STARTS",
        "SENDS_MAP",
        "RECEIVES_MAP",
        "JCL_STEP_RUNS",
        "READS",
        "WRITES",
        "UPDATES",
        "DELETES",
        "ENDS_BROWSE",
        "DEFINES_DATASET",
    }
