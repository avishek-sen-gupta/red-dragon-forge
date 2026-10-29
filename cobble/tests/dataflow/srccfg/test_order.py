"""Depth-first order over a CFG, and the edges that close a cycle.

Two properties carry the sweeping field walk. Reverse postorder is what makes a
single sweep exact on the acyclic part -- every predecessor a node is reached
through, back edges aside, is processed before it. The back-edge set is what one
sweep drops, so it is both what further sweeps recover and what a walk that stops
after the first has to report.
"""

from __future__ import annotations

from collections.abc import Sequence

from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.order import depth_first_order


def _cfg(edges: Sequence[tuple[str, str]], loose: Sequence[str] = ()) -> Cfg:
    """A graph of NOP nodes named by the edge list, in first-appearance order."""
    named = tuple(dict.fromkeys((*(node for pair in edges for node in pair), *loose)))
    return Cfg(
        program="PROGA",
        nodes=tuple(
            Node(id=name, kind=NodeKind.NOP, paragraph="MAIN") for name in named
        ),
        edges=tuple(
            Edge(source=source, target=target, kind=EdgeKind.FLOW)
            for source, target in edges
        ),
        entry="",
    )


def _position(order, node_id: str) -> int:
    return order.ordered.index(node_id)


def test_a_chain_orders_every_node_after_its_predecessor():
    order = depth_first_order(_cfg([("A", "B"), ("B", "C")]), "A")

    assert order.ordered == ("A", "B", "C")
    assert order.back_edges == frozenset()


def test_a_diamond_puts_the_merge_after_both_arms():
    order = depth_first_order(
        _cfg([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]), "A"
    )

    assert _position(order, "D") > _position(order, "B")
    assert _position(order, "D") > _position(order, "C")
    assert order.back_edges == frozenset()


def test_an_edge_closing_a_cycle_is_a_back_edge():
    order = depth_first_order(_cfg([("A", "B"), ("B", "C"), ("C", "B")]), "A")

    assert order.back_edges == frozenset(
        {Edge(source="C", target="B", kind=EdgeKind.FLOW)}
    )
    assert order.ordered == ("A", "B", "C")


def test_a_self_loop_is_a_back_edge():
    order = depth_first_order(_cfg([("A", "A")]), "A")

    assert order.back_edges == frozenset(
        {Edge(source="A", target="A", kind=EdgeKind.FLOW)}
    )


def test_an_edge_that_skips_ahead_over_a_chain_is_not_a_back_edge():
    """A forward edge reaches a finished node without closing a cycle. Dropping
    it would lose real flow, and the sweep drops exactly what this set holds."""
    order = depth_first_order(_cfg([("A", "B"), ("B", "C"), ("A", "C")]), "A")

    assert order.back_edges == frozenset()


def test_an_edge_between_two_branches_is_not_a_back_edge():
    order = depth_first_order(_cfg([("A", "B"), ("A", "C"), ("B", "C")]), "A")

    assert order.back_edges == frozenset()


def test_a_node_the_entry_cannot_reach_is_not_ordered():
    order = depth_first_order(_cfg([("A", "B")], loose=("DEAD",)), "A")

    assert order.ordered == ("A", "B")


def test_an_entry_the_graph_does_not_hold_orders_nothing():
    order = depth_first_order(_cfg([("A", "B")]), "MISSING")

    assert order.ordered == ()
    assert order.back_edges == frozenset()


def test_every_ordered_node_but_the_entry_has_a_forward_predecessor_before_it():
    """The invariant a one-pass sweep rests on: seeding only the entry is enough,
    because no reachable node is reached solely through a back edge."""
    cfg = _cfg(
        [
            ("A", "HEAD"),
            ("HEAD", "BODY"),
            ("BODY", "HEAD"),
            ("HEAD", "TAIL"),
            ("TAIL", "A"),
        ]
    )
    order = depth_first_order(cfg, "A")

    for node_id in order.ordered[1:]:
        forward = tuple(
            edge
            for edge in cfg.predecessors(node_id)
            if edge not in order.back_edges
            and _position(order, edge.source) < _position(order, node_id)
        )
        assert forward, node_id


def test_a_deep_chain_does_not_exhaust_the_interpreter_stack():
    """Real members run to thousands of nodes against a recursion limit of one."""
    depth = 5000
    edges = tuple((f"N{index}", f"N{index + 1}") for index in range(depth))

    order = depth_first_order(_cfg(edges), "N0")

    assert len(order.ordered) == depth + 1
