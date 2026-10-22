"""Which CICS verbs become graph edges.

The ported core maps a CicsVerb to at most one GraphEdge. A verb it has no branch
for is read from the source and thrown away silently, which is how EXEC CICS
START went missing: 3,024 statements across 876 members of the onboarding corpus
named a transaction that never reached the graph.
"""

from __future__ import annotations

from cobble.cics.flow_graph_core import _verb_edge
from cobble.cics.flow_observer import CicsVerb
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind


def _verb(verb: str, **operands) -> CicsVerb:
    return CicsVerb(verb=verb, program="SOMEPROG", **operands)


def _edge_fields(verb: CicsVerb) -> tuple:
    """The edge a verb makes, as endpoints and kind, or () when it makes none."""
    match _verb_edge(verb, {}):
        case (edge,):
            return (
                edge.source,
                edge.source_kind,
                edge.target,
                edge.target_kind,
                edge.kind,
            )
        case _:
            return ()


def test_starting_a_transaction_is_an_edge_to_that_transaction() -> None:
    """EXEC CICS START TRANSID(...) is how asynchronous work is dispatched: the
    program names a transaction it does not transfer to and does not return to.

    Without this branch such a program appears to reach nothing, and a transaction
    only ever started -- 33 of the 48 the onboarding corpus cannot place -- has no
    node from any path at all.
    """
    assert _edge_fields(_verb("START_TRANSID", transid="a123")) == (
        "SOMEPROG",
        NodeKind.PROGRAM,
        "A123",
        NodeKind.TRANSACTION,
        EdgeKind.START_TRANSID,
    )


def test_a_start_that_names_no_transaction_is_not_an_edge() -> None:
    """START also carries TERMID/INTERVAL/FROM. With a TRANSID the parser could
    not resolve to a literal there is no transaction to point at, and an edge to
    the empty string is worse than no edge."""
    assert _edge_fields(_verb("START_TRANSID")) == ()


def test_returning_to_a_transaction_still_maps_as_before() -> None:
    """The verb the new branch sits next to, pinned so the two stay distinct:
    RETURN_TRANSID is the program handing control back, START_TRANSID is it
    dispatching work that outlives the current task."""
    assert _edge_fields(_verb("RETURN_TRANSID", transid="B456")) == (
        "SOMEPROG",
        NodeKind.PROGRAM,
        "B456",
        NodeKind.TRANSACTION,
        EdgeKind.RETURN_TRANSID,
    )


def test_a_file_verb_naming_a_literal_file_is_an_edge_and_a_data_item_is_not() -> None:
    """A literal FILE(...) is the whole answer, so the verb's own edge names it.
    A file named through a data item has no file_name -- the dataflow's targets
    table, or the not-attempted marking, gives that site its edge instead."""
    assert [
        _edge_fields(_verb(verb, file_name="usrsec"))
        for verb in ("READ", "STARTBR", "WRITE", "REWRITE", "DELETE", "ENDBR")
    ] == [
        ("SOMEPROG", NodeKind.PROGRAM, "USRSEC", NodeKind.CICS_FILE, kind)
        for kind in (
            EdgeKind.READS,
            EdgeKind.READS,
            EdgeKind.WRITES,
            EdgeKind.UPDATES,
            EdgeKind.DELETES,
            EdgeKind.ENDS_BROWSE,
        )
    ]
    assert _edge_fields(_verb("READ", file_operand="WS-USRSEC-FILE")) == ()
