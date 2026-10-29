"""The graph vocabulary. Everything downstream is written against these types, so
the invariants that matter are structural: a TEST has exactly two out-edges, a
fragment's exits are the only place the next statement may attach, and sequencing
two fragments consumes every exit of the first."""

from __future__ import annotations

import pytest

from cobble.dataflow.srccfg.cfg import (
    EMPTY_FRAGMENT,
    UNRESOLVED,
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Exit,
    Fragment,
    Node,
    NodeKind,
    merge,
    seq,
)


def _assign(node_id: str, writes: tuple[str, ...] = ("WS-A",)) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.ASSIGN,
        paragraph="MAIN",
        atom=UNRESOLVED,
        writes=writes,
        reads=("WS-B",),
        transfer="MOVE",
        target="",
    )


def _fragment(node_id: str) -> Fragment:
    """One ASSIGN node with one dangling FLOW exit -- the shape every
    straight-line statement lowers to."""
    return Fragment(
        nodes=(_assign(node_id),),
        edges=(),
        entry=node_id,
        exits=(Exit(node_id=node_id, kind=EdgeKind.FLOW),),
    )


def test_an_atom_carries_its_own_source_text() -> None:
    """The text is what a report shows a human; the parts are what a query filters
    on. Both are needed, so both are stored rather than reconstructed."""
    atom = Atom(text="WS-FLAG-A = 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert atom.resolved is True
    assert (atom.left, atom.op, atom.right) == ("WS-FLAG-A", "==", "'Y'")


def test_the_unresolved_atom_is_a_value_not_an_absence() -> None:
    """A predicate the ASG gives as opaque text -- SEARCH WHEN, a computed
    condition -- must still occupy a node, because a path through it is a real
    path. Dropping it would silently strengthen every condition downstream."""
    assert UNRESOLVED.resolved is False
    assert UNRESOLVED.left == ""


def test_a_fragment_with_no_nodes_has_no_entry_and_no_exits() -> None:
    assert EMPTY_FRAGMENT.nodes == ()
    assert EMPTY_FRAGMENT.entry == ""
    assert EMPTY_FRAGMENT.exits == ()


def test_sequencing_wires_every_exit_of_the_first_into_the_second() -> None:
    """An IF fragment leaves two exits, one per arm. Both continue into whatever
    follows the END-IF, so seq must attach all of them -- attaching only the last
    is the classic way an arm's assignments lose their successors."""
    left = Fragment(
        nodes=(_assign("a"), _assign("b")),
        edges=(),
        entry="a",
        exits=(
            Exit(node_id="a", kind=EdgeKind.TRUE),
            Exit(node_id="b", kind=EdgeKind.FALSE),
        ),
    )

    joined = seq((left, _fragment("c")), nop_id="unused")

    assert joined.entry == "a"
    assert set(joined.edges) == {
        Edge(source="a", target="c", kind=EdgeKind.TRUE),
        Edge(source="b", target="c", kind=EdgeKind.FALSE),
    }
    assert joined.exits == (Exit(node_id="c", kind=EdgeKind.FLOW),)


def test_sequencing_an_empty_fragment_changes_nothing() -> None:
    """A statement that lowers to nothing -- a comment-only paragraph, a verb with
    no dataflow and no control effect -- must not break the chain around it."""
    only = _fragment("a")

    assert seq((EMPTY_FRAGMENT, only, EMPTY_FRAGMENT), nop_id="unused") == only


def test_sequencing_nothing_is_empty() -> None:
    assert seq((), nop_id="unused") == EMPTY_FRAGMENT


def test_a_fragment_whose_exits_are_all_consumed_ends_the_chain() -> None:
    """A GO TO fragment has no exits: control leaves for a label. Anything
    sequenced after it is unreachable, and must not be wired to it."""
    goes = Fragment(nodes=(_assign("a"),), edges=(), entry="a", exits=())

    joined = seq((goes, _fragment("b")), nop_id="unused")

    assert joined.edges == ()
    assert joined.entry == "a"
    assert joined.exits == (Exit(node_id="b", kind=EdgeKind.FLOW),)


def test_merge_collects_nodes_and_edges_without_wiring_them() -> None:
    """Paragraph fragments are collected before their PERFORM and GO TO edges can
    be resolved, so there is a step that unions without sequencing."""
    merged = merge((_fragment("a"), _fragment("b")))

    assert [node.id for node in merged.nodes] == ["a", "b"]
    assert merged.edges == ()
    assert merged.entry == "a"


def test_a_cfg_indexes_successors_and_predecessors_by_node() -> None:
    cfg = Cfg(
        program="PROGA",
        nodes=(_assign("a"), _assign("b")),
        edges=(Edge(source="a", target="b", kind=EdgeKind.FLOW),),
        entry="",
    )

    assert cfg.successors("a") == (Edge(source="a", target="b", kind=EdgeKind.FLOW),)
    assert cfg.predecessors("b") == (Edge(source="a", target="b", kind=EdgeKind.FLOW),)
    assert cfg.successors("b") == ()
    assert cfg.node("b").writes == ("WS-A",)


def test_asking_for_a_node_that_is_not_there_raises() -> None:
    """A missing node means an edge was built against an id nothing emitted --
    always a bug in lowering, never a query a caller should get an answer to."""
    cfg = Cfg(program="PROGA", nodes=(), edges=(), entry="")

    with pytest.raises(KeyError):
        cfg.node("a")
