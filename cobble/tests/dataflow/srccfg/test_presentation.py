"""What a CFG node is called, and which CALLs resolve inside a bundle.

Both renderers read this, so a test here is a test that they cannot disagree about
what a node says: two pictures of one program that label the same node differently
are two pictures of different programs.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.presentation import (
    CrossCall,
    label_of,
    qualified,
    resolved_calls,
)


def _label(paragraph: str) -> Node:
    return Node(id=f"{paragraph}#label", kind=NodeKind.LABEL, paragraph=paragraph)


def _call(node_id: str, program: str) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.CALL,
        paragraph="MAIN",
        transfer="CICS_LINK",
        target=program,
    )


def _caller(callee: str, program: str = "PROGA") -> Cfg:
    return Cfg(
        program=program,
        nodes=(_label("MAIN"), _call("MAIN/0", callee)),
        edges=(Edge(source="MAIN#label", target="MAIN/0", kind=EdgeKind.FLOW),),
    )


def _callee(program: str = "PROGB") -> Cfg:
    return Cfg(program=program, nodes=(_label("MAIN"),), edges=())


def test_a_node_id_is_qualified_with_its_program() -> None:
    """Every member of a corpus has a MAIN/0, and an unqualified id merges them."""
    assert qualified("PROGA", "MAIN/0") == "PROGA::MAIN/0"


def test_a_test_node_reads_as_its_predicate() -> None:
    node = Node(
        id="MAIN/0",
        kind=NodeKind.TEST,
        paragraph="MAIN",
        atom=Atom(text="WS-FLAG-A == 'A'", left="WS-FLAG-A", op="==", right="'A'"),
    )

    assert label_of(node) == "WS-FLAG-A == 'A'"


def test_an_assignment_reads_as_the_verb_and_what_it_writes() -> None:
    node = Node(
        id="MAIN/0",
        kind=NodeKind.ASSIGN,
        paragraph="MAIN",
        writes=("WS-OUT",),
        transfer="MOVE",
    )

    assert label_of(node) == "MOVE WS-OUT"


def test_a_call_reads_as_the_verb_and_its_target() -> None:
    assert label_of(_call("MAIN/0", "PROGB")) == "CICS_LINK PROGB"


def test_a_paragraph_label_reads_as_the_paragraph() -> None:
    assert label_of(_label("READ-CUSTOMER")) == "READ-CUSTOMER"


def test_a_nop_reads_as_its_id() -> None:
    """A NOP has nothing to say about itself, and a blank node reads as a bug."""
    node = Node(id="MAIN/3", kind=NodeKind.NOP, paragraph="MAIN")

    assert label_of(node) == "MAIN/3"


def test_a_call_to_a_program_in_the_bundle_resolves_to_that_program_s_entry() -> None:
    assert resolved_calls((_caller("PROGB"), _callee())) == (
        CrossCall(
            source="PROGA::MAIN/0", target="PROGB::MAIN#label", transfer="CICS_LINK"
        ),
    )


def test_a_call_to_a_program_not_in_the_bundle_resolves_to_nothing() -> None:
    """Its ASG was never in the cache, so it has no nodes here; an edge to a node
    that does not exist draws a program that looks built and is not."""
    assert resolved_calls((_caller("PROGZ"),)) == ()


def test_a_program_with_no_calls_resolves_to_nothing() -> None:
    assert resolved_calls((_callee(),)) == ()


def test_a_callee_with_no_nodes_resolves_to_nothing() -> None:
    """An empty CFG has no entry to point at."""
    empty = Cfg(program="PROGB", nodes=(), edges=())

    assert resolved_calls((_caller("PROGB"), empty)) == ()
