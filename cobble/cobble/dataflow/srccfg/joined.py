"""A bundle's CFGs as one graph, joined at the calls that cross between them.

A bundle is a tuple of CFGs with no edges between them: EdgeKind is intra-program
throughout and node ids are program-local, so two members' MAIN/0 are the same id
and different nodes. Every consumer that wants to cross therefore has to qualify the
ids and add the call edges itself -- and two consumers that do it differently read
two different graphs out of one file.

So it is done here, once. The renderers draw what this returns; a traversal walks it.
``calls`` is the bundle's own, when the file carried them; without it the join is
derived from the CFGs, which is what a per-member CFG file needs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum

import networkx as nx
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.presentation import cross_calls, label_of, qualified
from cobble.knowledge_graph.drawn_node import DrawnNode


class CallKind(Enum):
    """The one edge that is not in any CFG: a CALL joined to its callee's entry.

    Its own kind and not an EdgeKind, because it crosses a program boundary and
    nothing inside one program's CFG does -- and because the legend has to be able
    to name it.
    """

    CALL = "CALL"
    CALL_CANDIDATE = "CALL_CANDIDATE"


def drawn_nodes_of(cfgs: Sequence[Cfg]) -> Mapping[str, DrawnNode]:
    """Every node's graph key, looked up by the qualified id an edge names it by."""
    return {
        qualified(cfg.program, node.id): (node.kind, qualified(cfg.program, node.id))
        for cfg in cfgs
        for node in cfg.nodes
    }


def graph_of(cfgs: Sequence[Cfg], calls: Sequence[BundleCall] = ()) -> nx.MultiDiGraph:
    """The bundle as one graph, keyed (kind, qualified id).

    The corpus graph is keyed the same way, so sfdp_positions and render_webgl_html
    index this unchanged. The label carries the program because "MOVE WS-FLAG-A"
    occurs in a dozen members of a closure and a page that does not say which one
    leaves the reader nowhere.
    """
    drawn = drawn_nodes_of(cfgs)
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(_nodes_of(cfgs, drawn))
    graph.add_edges_from(_flow_edges(cfgs, drawn))
    graph.add_edges_from(_call_edges(cfgs, drawn, calls))
    return graph


def _nodes_of(cfgs: Sequence[Cfg], drawn: Mapping[str, DrawnNode]) -> tuple:
    return tuple(
        (
            drawn[qualified(cfg.program, node.id)],
            {"kind": node.kind, "id": f"{cfg.program} {label_of(node)}"},
        )
        for cfg in cfgs
        for node in cfg.nodes
    )


def _flow_edges(cfgs: Sequence[Cfg], drawn: Mapping[str, DrawnNode]) -> tuple:
    return tuple(
        (
            drawn[qualified(cfg.program, edge.source)],
            drawn[qualified(cfg.program, edge.target)],
            {"kind": edge.kind},
        )
        for cfg in cfgs
        for edge in cfg.edges
    )


def _call_edges(
    cfgs: Sequence[Cfg], drawn: Mapping[str, DrawnNode], calls: Sequence[BundleCall]
) -> tuple:
    return tuple(
        (
            drawn[call.source],
            drawn[call.target],
            {"kind": CallKind.CALL if call.certain else CallKind.CALL_CANDIDATE},
        )
        for call in cross_calls(cfgs, calls)
    )
