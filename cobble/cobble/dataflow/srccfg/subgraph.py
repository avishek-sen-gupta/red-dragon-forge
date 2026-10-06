"""Render a hand-picked subgraph of a cobble-srccfg-build CFG as Graphviz.

Generalizes the recipe for picking a handful of nodes relevant to one
question out of a program's (or several programs' closure's) full CFG:
pick nodes by id-prefix, label TEST/ASSIGN/CALL nodes with their real
condition/MOVE/PERFORM text (not just the bare ``kind``), auto-bridge
disconnected pieces back to the main component, drop noise nodes, and hand
back a DOT document plus which nodes were bridged in.

PREFIX MATCHING IS SEPARATOR-AWARE: a prefix of ``READ-RECORD/1`` matches
``READ-RECORD/1``, ``.../1.sql0#test``, ``.../1#test`` -- NOT ``.../10``,
``.../11``, ... A bare ``str.startswith`` would wrongly pull those in.

CONNECTIVITY IS ENFORCED. After prefix-matching, if the result has more
than one weakly-connected component, each smaller component is bridged to
the largest one by the shortest path through the FULL graph (not just the
filtered edges) -- i.e. it pulls in whatever ancestor/intermediate nodes
are needed to make the picture whole, and reports exactly which ones. If
no path exists at all between two pieces, that's a hard error rather than
silently rendering a disconnected graph.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate, dropwhile, repeat

from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind

Pair = tuple[str, str]
_LabelFn = Callable[[Node], str]


class SubgraphError(ValueError):
    """A requested subgraph that cannot be built as asked."""


def matches(node_id: str, prefix: str) -> bool:
    """Separator-aware: ``node_id`` must equal ``prefix`` or continue with a
    structural separator (``/``, ``#``, ``.``), never just share leading digits.
    """
    return (
        node_id == prefix
        or node_id.startswith(prefix + "/")
        or node_id.startswith(prefix + "#")
        or node_id.startswith(prefix + ".")
    )


# --- node labelling ----------------------------------------------------------


def _shortened(node_id: str, short_prefixes: Mapping[str, str]) -> str:
    return reduce(lambda nid, pair: nid.replace(*pair), short_prefixes.items(), node_id)


def _test_label(node: Node) -> str:
    if node.atom.resolved:
        return node.atom.text
    return "(raised condition?)"


def _fallback_label(node: Node) -> str:
    if not node.transfer:
        return node.kind.value
    extra = f" -> {node.target}" if node.target else ""
    return f"{node.transfer}{extra}"


def _assign_label(node: Node) -> str:
    if node.transfer != "MOVE":
        return _fallback_label(node)
    return f"MOVE {', '.join(node.reads)} TO {', '.join(node.writes)}"


def _perform_label(node: Node) -> str:
    return f"PERFORM {node.target}"


def _goto_depending_label(node: Node) -> str:
    return f"GO TO ... DEPENDING ON {', '.join(node.reads)}"


def _goto_label(node: Node) -> str:
    return f"GO TO {node.target}"


def _cics_label(verb: str, node: Node) -> str:
    return f"EXEC CICS {verb}\\nPROGRAM('{node.target}')\\nCOMMAREA({node.transfer_operand})"


def _cics_link_label(node: Node) -> str:
    return _cics_label("LINK", node)


def _cics_xctl_label(node: Node) -> str:
    return _cics_label("XCTL", node)


def _call_label(node: Node) -> str:
    return _TRANSFER_LABELS.get(node.transfer, _fallback_label)(node)


def _label_label(_node: Node) -> str:
    return "(paragraph entry)"


_TRANSFER_LABELS: Mapping[str, _LabelFn] = {
    "PERFORM": _perform_label,
    "GO TO DEPENDING": _goto_depending_label,
    "GO TO": _goto_label,
    "CICS_LINK": _cics_link_label,
    "CICS_XCTL": _cics_xctl_label,
}


def node_label(node: Node, short_prefixes: Mapping[str, str]) -> str:
    """A richer, per-node label than ``presentation.label_of`` -- deliberately
    so: that function labels every node of a dense, thousands-of-nodes full
    CFG render, where compactness matters more than any one node's detail.
    This one labels a small, hand-picked subgraph meant for a person (or an
    LLM) to read standalone without the source open beside it, so it spells
    out the actual MOVE operands, PERFORM/GOTO target, or CICS verb+program
    rather than just the transfer keyword.
    """
    nid = _shortened(node.id, short_prefixes)
    body = _KIND_LABELS[node.kind](node)
    return f"{nid}\\n{body}"


_KIND_LABELS: Mapping[NodeKind, _LabelFn] = {
    NodeKind.TEST: _test_label,
    NodeKind.ASSIGN: _assign_label,
    NodeKind.CALL: _call_label,
    NodeKind.LABEL: _label_label,
    NodeKind.NOP: _fallback_label,
}


# --- connectivity -------------------------------------------------------------


def _touching(
    comps: tuple[frozenset[str], ...], *nodes: str
) -> tuple[frozenset[str], ...]:
    return tuple(comp for comp in comps if any(node in comp for node in nodes))


def _merged(
    comps: tuple[frozenset[str], ...], edge: Pair
) -> tuple[frozenset[str], ...]:
    source, target = edge
    hit = _touching(comps, source, target)
    if len(hit) <= 1:
        return comps
    rest = tuple(comp for comp in comps if comp not in hit)
    return (*rest, hit[0] | hit[1])


def _components(
    node_ids: frozenset[str], edges: Sequence[Pair]
) -> tuple[frozenset[str], ...]:
    singles = tuple(frozenset({node}) for node in node_ids)
    return reduce(_merged, edges, singles)


def _within(focus: frozenset[str], edges: Sequence[Pair]) -> tuple[Pair, ...]:
    return tuple((s, t) for s, t in edges if s in focus and t in focus)


def _adjacency(edges: Sequence[Pair]) -> Mapping[str, frozenset[str]]:
    pairs = tuple(edges) + tuple((t, s) for s, t in edges)
    nodes = frozenset(node for pair in pairs for node in pair)
    return {node: frozenset(t for s, t in pairs if s == node) for node in nodes}


@dataclass(frozen=True)
class _Frontier:
    paths: tuple[tuple[str, ...], ...]
    seen: frozenset[str]
    found: tuple[str, ...] = ()


def _neighbors(
    adjacency: Mapping[str, frozenset[str]], seen: frozenset[str], path: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        (*path, nxt) for nxt in adjacency.get(path[-1], frozenset()) if nxt not in seen
    )


def _grown(
    adjacency: Mapping[str, frozenset[str]],
    seen: frozenset[str],
    paths: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(step for path in paths for step in _neighbors(adjacency, seen, path))


def _settled(
    targets: frozenset[str], seen: frozenset[str], grown: tuple[tuple[str, ...], ...]
) -> _Frontier:
    hits = tuple(path for path in grown if path[-1] in targets)
    return _Frontier(
        paths=grown,
        seen=seen | frozenset(path[-1] for path in grown),
        found=hits[0] if hits else (),
    )


def _advanced_frontier(
    adjacency: Mapping[str, frozenset[str]],
    targets: frozenset[str],
    frontier: _Frontier,
) -> _Frontier:
    if not frontier.paths:
        return frontier
    return _settled(
        targets, frontier.seen, _grown(adjacency, frontier.seen, frontier.paths)
    )


def _still_searching(frontier: _Frontier) -> bool:
    return not frontier.found and bool(frontier.paths)


def _shortest_path(
    all_edges: Sequence[Pair], sources: frozenset[str], targets: frozenset[str]
) -> tuple[str, ...]:
    """BFS over the full graph, undirected (a control-flow bridge may be an
    ancestor feeding both pieces, found by walking edges backward from
    either side), shortest path from any node in ``sources`` to any node in
    ``targets``. An empty tuple means no path exists."""
    adjacency = _adjacency(all_edges)
    begun = _Frontier(paths=tuple((source,) for source in sources), seen=sources)
    levels = accumulate(
        repeat(begun),
        lambda frontier, _step: _advanced_frontier(adjacency, targets, frontier),
        initial=begun,
    )
    settled = next(dropwhile(_still_searching, levels))
    return settled.found


@dataclass(frozen=True)
class _Bridge:
    focus: frozenset[str]
    added: tuple[str, ...]
    used_weak: bool


def _one_bridge(
    all_edges: Sequence[Pair],
    strong_edges: Sequence[Pair],
    comps: tuple[frozenset[str], ...],
) -> tuple[tuple[str, ...], bool]:
    by_size = sorted(comps, key=len, reverse=True)
    anchor, gap = by_size[0], by_size[-1]
    strong_path = _shortest_path(strong_edges, gap, anchor)
    if strong_path:
        return strong_path, False
    weak_path = _shortest_path(all_edges, gap, anchor)
    if weak_path:
        return weak_path, True
    raise SubgraphError(
        f"no path at all between {sorted(gap)[:3]}... and the rest of the "
        "requested nodes -- these pieces are genuinely unrelated in this "
        "CFG; don't render them together, or check the prefixes for a typo."
    )


def _one_bridge_round(
    all_edges: Sequence[Pair], strong_edges: Sequence[Pair], state: _Bridge
) -> _Bridge:
    comps = _components(state.focus, _within(state.focus, all_edges))
    if len(comps) <= 1:
        return state
    path, used_weak = _one_bridge(all_edges, strong_edges, comps)
    new = tuple(node for node in path if node not in state.focus)
    return _Bridge(
        focus=state.focus | frozenset(new),
        added=(*state.added, *new),
        used_weak=state.used_weak or used_weak,
    )


def _still_bridging(all_edges: Sequence[Pair], state: _Bridge) -> bool:
    return len(_components(state.focus, _within(state.focus, all_edges))) > 1


def bridged_focus(
    focus: set[str],
    all_edges: Sequence[Pair],
    strong_edges: Sequence[Pair],
) -> tuple[set[str], list[str], bool]:
    """Grow ``focus`` until it is one weakly-connected component.

    Tries a path through ``strong_edges`` first (every real jump: GOTO,
    PERFORM, CALL/LINK/XCTL, RETURN, TRUE/FALSE) -- a provable control-flow
    connection, e.g. the real PERFORM into a paragraph that was forgotten.
    Only if no such path exists does it fall back to ``all_edges`` (adds
    FALLTHRU: textual adjacency, which COBOL permits as a real control
    transfer but which a long chain of unrelated paragraphs also shares
    merely by sitting next to each other in the source -- a fallback bridge
    is reported as such, not blended in silently).

    Returns the enlarged set, the nodes added as bridges, and whether the
    weak (FALLTHRU) fallback was needed. Raises ``SubgraphError`` if no path
    exists at all.
    """
    begun = _Bridge(focus=frozenset(focus), added=(), used_weak=False)
    rounds = accumulate(
        repeat(begun),
        lambda state, _step: _one_bridge_round(all_edges, strong_edges, state),
        initial=begun,
    )
    settled = next(dropwhile(lambda state: _still_bridging(all_edges, state), rounds))
    return set(settled.focus), list(settled.added), settled.used_weak


# --- DOT rendering -------------------------------------------------------------


def _kind_fill(kind: NodeKind) -> str:
    if kind is NodeKind.LABEL:
        return "lightyellow"
    if kind is NodeKind.TEST:
        return "lightblue"
    return "white"


def _fill(node: Node, bridge_added: Sequence[str]) -> str:
    if node.id in bridge_added:
        return "lightgray"  # visibly distinct: pulled in to keep the graph connected
    return _kind_fill(node.kind)


def _node_line(
    node: Node, bridge_added: Sequence[str], short_prefixes: Mapping[str, str]
) -> str:
    return f'  "{node.id}" [label="{node_label(node, short_prefixes)}", style=filled, fillcolor={_fill(node, bridge_added)}];'


_EDGE_STYLES: Mapping[EdgeKind, str] = {
    EdgeKind.TRUE: ' [label="TRUE", style=dashed]',
    EdgeKind.FALSE: ' [label="FALSE", style=dashed]',
    EdgeKind.GOTO: ' [label="GOTO", color=blue, penwidth=2]',
    EdgeKind.PERFORM: ' [label="PERFORM", color=darkgreen]',
    EdgeKind.FALLTHRU: ' [label="fallthru", style=dotted, color=gray]',
    EdgeKind.RETURN: " [style=dotted, color=gray]",
}


def _edge_line(edge: Edge) -> str:
    return f'  "{edge.source}" -> "{edge.target}"{_EDGE_STYLES.get(edge.kind, "")};'


def _focused_dot(
    focus: frozenset[str],
    nodes: Mapping[str, Node],
    rel_edges: Sequence[Edge],
    bridge_added: Sequence[str],
    short_prefixes: Mapping[str, str],
) -> str:
    node_lines = (
        _node_line(nodes[nid], bridge_added, short_prefixes) for nid in sorted(focus)
    )
    edge_lines = (_edge_line(edge) for edge in rel_edges)
    header = (
        "digraph subgraph_cfg {",
        '  rankdir=TB; node [shape=box, fontsize=9, fontname="monospace"];',
    )
    return "\n".join((*header, *node_lines, *edge_lines, "}"))


def build_dot(
    cfgs: Sequence[Cfg],
    prefixes: Sequence[str],
    drop_suffixes: Sequence[str],
    drop_targets: frozenset[str],
    short_prefixes: Mapping[str, str],
) -> tuple[str, list[str], bool]:
    """The DOT document for the nodes matching any of ``prefixes`` across
    ``cfgs``, connectivity-bridged. Returns ``(document, bridged_node_ids,
    used_weak_fallback)``.
    """
    nodes: Mapping[str, Node] = {node.id: node for cfg in cfgs for node in cfg.nodes}
    edges = tuple(edge for cfg in cfgs for edge in cfg.edges)
    all_edges = tuple((edge.source, edge.target) for edge in edges)
    strong_edges = tuple(
        (edge.source, edge.target) for edge in edges if edge.kind != EdgeKind.FALLTHRU
    )

    matched = frozenset(
        nid for nid in nodes if any(matches(nid, prefix) for prefix in prefixes)
    )
    without_dropped = frozenset(
        nid
        for nid in matched
        if not any(nid.endswith(suffix) for suffix in drop_suffixes)
    )

    focus, bridge_added, used_weak = bridged_focus(
        set(without_dropped), all_edges, strong_edges
    )
    frozen_focus = frozenset(focus)
    rel_edges = tuple(
        edge
        for edge in edges
        if edge.source in frozen_focus
        and edge.target in frozen_focus
        and edge.target not in drop_targets
    )
    return (
        _focused_dot(frozen_focus, nodes, rel_edges, bridge_added, short_prefixes),
        bridge_added,
        used_weak,
    )
