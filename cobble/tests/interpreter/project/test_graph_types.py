from pathlib import Path

import pytest

from cobble.file_location import FileLocationReason, NoFileLocation
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def test_graph_node_equality_is_by_value() -> None:
    a = GraphNode(
        id="ACCTFILE", kind=NodeKind.PROGRAM, location=Path("app/cbl/ACCTFILE.cbl")
    )
    b = GraphNode(
        id="ACCTFILE", kind=NodeKind.PROGRAM, location=Path("app/cbl/ACCTFILE.cbl")
    )
    assert a == b


def test_a_node_carries_why_it_has_no_file_not_merely_that_it_has_none() -> None:
    """A node's location is a FileLocation, not a collapsed str | None, so the
    reason survives all the way to serialisation instead of being thrown away
    at construction by whichever extractor built the node."""
    missing = GraphNode(
        id="PROGONE",
        kind=NodeKind.PROGRAM,
        location=NoFileLocation(FileLocationReason.UNRESOLVED),
    )
    never_had_one = GraphNode(
        id="TEST.DATA",
        kind=NodeKind.DATASET,
        location=NoFileLocation(FileLocationReason.NOT_FILE_BASED),
    )

    assert missing.location != never_had_one.location


def test_graph_node_defaults_to_having_asked_nobody() -> None:
    """Not UNRESOLVED: a node built without a CorpusIndex has not failed to
    resolve, it has never been looked up."""
    node = GraphNode(id="COACTVW", kind=NodeKind.PROGRAM)
    assert node.location == NoFileLocation(FileLocationReason.NOT_ATTEMPTED)
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
        "START_TRANSID",
        "SENDS_MAP",
        "RECEIVES_MAP",
        "JCL_STEP_RUNS",
        "TSO_RUNS_PROGRAM",
        "READS",
        "WRITES",
        "UPDATES",
        "DELETES",
        "ENDS_BROWSE",
        "DEFINES_DATASET",
    }
