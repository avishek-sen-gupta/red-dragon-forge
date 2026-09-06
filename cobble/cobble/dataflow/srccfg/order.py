"""Depth-first order over a CFG, and the edges that close a cycle.

Reverse postorder is what lets one sweep be exact on the acyclic part of a
graph: every predecessor a node is reached through, back edges aside, is
processed before it. So a walk that visits in this order and drops back edges
needs no iteration at all -- and the back-edge set is what it dropped, which is
the only thing that makes such a result readable as an under-approximation
rather than mistakable for an answer.

The search is iterative because a recursive one cannot run on a real member: the
corpus's larger programs reach thousands of nodes against an interpreter
recursion limit of a thousand frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cobble.dataflow.srccfg.cfg import Cfg, Edge


@dataclass(frozen=True)
class DepthFirstOrder:
    """``ordered`` is reverse postorder from the entry, ``back_edges`` the rest.

    Only nodes the entry reaches are ordered. An unreachable node has no entry
    state to compute, which is what the worklist walk already does with it.
    """

    ordered: tuple[str, ...] = ()
    back_edges: frozenset[Edge] = field(default_factory=frozenset)


def depth_first_order(cfg: Cfg, entry: str) -> DepthFirstOrder:
    """Depth-first search from ``entry``, classifying every edge it leaves by.

    An edge is a back edge when its target is still on the search path: that is
    what distinguishes it from a forward or cross edge, which reaches a finished
    node without closing a cycle and carries flow a sweep must keep.
    """
    if entry not in cfg.node_ids:
        return DepthFirstOrder()
    postorder: list[str] = []
    back: set[Edge] = set()
    on_path = {entry}
    finished: set[str] = set()
    stack = [(entry, iter(cfg.successors(entry)))]
    while stack:
        node_id, remaining = stack[-1]
        edge = next(remaining, None)
        if edge is None:
            stack.pop()
            on_path.discard(node_id)
            finished.add(node_id)
            postorder.append(node_id)
        elif edge.target in on_path:
            back.add(edge)
        elif edge.target not in finished:
            on_path.add(edge.target)
            stack.append((edge.target, iter(cfg.successors(edge.target))))
    return DepthFirstOrder(tuple(reversed(postorder)), frozenset(back))
