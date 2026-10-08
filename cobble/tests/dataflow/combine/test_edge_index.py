"""EdgeIndex: a round's edges grouped by what each stop follows, the same edges a scan would pick."""

from cobble.dataflow.combine.edge import Edge
from cobble.dataflow.combine.edge_index import edge_index
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.jumps.jump_kind import JumpKind


def _edge(caller: str, node: str, kind: JumpKind, callee: str, param: int = 0) -> Edge:
    return Edge(
        caller,
        node,
        kind,
        callee,
        param,
        byte_range("WS-AREA@working_storage[0:8]", caller),
        byte_range("DFHCOMMAREA@linkage[0:8]", callee),
        callee_node="R" if kind is JumpKind.START else "",
    )


def test_edges_are_found_by_what_each_stop_follows() -> None:
    xctl = _edge("A", "X", JumpKind.XCTL, "B")
    link = _edge("C", "L", JumpKind.LINK, "B")
    call = _edge("C", "K", JumpKind.CALL, "B", param=1)
    transid = _edge("D", "T", JumpKind.RETURN_TRANSID, "B")
    start = _edge("E", "S", JumpKind.START, "B")

    index = edge_index(frozenset({xctl, link, call, transid, start}))

    assert {where: frozenset(edges) for where, edges in index.into.items()} == {
        ("B", 0): frozenset({xctl, link, transid}),
        ("B", 1): frozenset({call}),
    }
    assert dict(index.out) == {
        ("A", "X", 0): (xctl,),
        ("C", "L", 0): (link,),
        ("C", "K", 1): (call,),
        ("D", "T", 0): (transid,),
        ("E", "S", 0): (start,),
    }
    assert dict(index.started) == {("B", "R"): (start,)}
    assert (
        dict(edge_index(frozenset()).into),
        dict(edge_index(frozenset()).out),
        dict(edge_index(frozenset()).started),
    ) == ({}, {}, {})
