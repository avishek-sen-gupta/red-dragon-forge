"""Builds the field graph: each dep row and link mapped onto the elementary fields it moves."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from itertools import groupby, product

from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.trace_query import DepRow
from cobble.experimental.partition.barrier import Barrier
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.field_leaf import FieldLeaf
from cobble.experimental.partition.flow import Flow
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.leaf_index import LeafIndex
from cobble.experimental.partition.link_row import LinkRow
from cobble.experimental.partition.node_kind import NodeKind

_Moved = tuple[tuple[GraphNode, ...], tuple[Flow, ...]]
_Pair = tuple[FieldLeaf, FieldLeaf]


def _field(leaf: FieldLeaf) -> GraphNode:
    return GraphNode(
        id=leaf.node,
        kind=NodeKind.FIELD,
        label=f"{leaf.program}.{leaf.name}",
        program=leaf.program,
        record=leaf.record,
        pic=leaf.pic,
    )


def _terminal(kind: NodeKind, program: str, name: str) -> GraphNode:
    return GraphNode(
        id=f"{program}|{kind}|{name}",
        kind=kind,
        label=f"{program} {name}",
        program=program,
    )


def _aligned(target: ByteRange, source: ByteRange, leaf: FieldLeaf) -> tuple[int, int]:
    shift = source.start - target.start
    return max(leaf.start, target.start) + shift, min(leaf.end, target.end) + shift


def _pairs(
    targets: tuple[FieldLeaf, ...],
    sources: tuple[FieldLeaf, ...],
    target: ByteRange,
    source: ByteRange,
) -> tuple[_Pair, ...]:
    if len(targets) == 1 or len(sources) == 1:
        return tuple((s, t) for s, t in product(sources, targets))
    return tuple(
        (s, t)
        for t in targets
        for start, end in (_aligned(target, source, t),)
        for s in sources
        if s.overlaps(start, end)
    )


def _copied(
    index: LeafIndex, barrier: Barrier, target: ByteRange, source: ByteRange, site: str
) -> _Moved:
    pairs = _pairs(index.fields_in(target), index.fields_in(source), target, source)
    clustered = not barrier.blocks({(s.node, t.node) for s, t in pairs})
    return (
        tuple(_field(leaf) for pair in pairs for leaf in pair),
        tuple(Flow(s.node, t.node, site, clustered) for s, t in pairs),
    )


def _fanned(
    terminal: GraphNode, leaves: tuple[FieldLeaf, ...], site: str, *, inward: bool
) -> _Moved:
    return (
        (terminal, *(_field(leaf) for leaf in leaves)),
        tuple(
            (
                Flow(terminal.id, leaf.node, site, True)
                if inward
                else Flow(leaf.node, terminal.id, site, True)
            )
            for leaf in leaves
        ),
    )


def _moved(index: LeafIndex, barrier: Barrier, dep: DepRow) -> _Moved:
    if dep.sink:
        sink = _terminal(NodeKind.SINK, dep.source.program, dep.sink)
        return _fanned(sink, index.fields_in(dep.source), dep.site, inward=False)
    if not dep.source.known:
        origin = _terminal(NodeKind.ORIGIN, dep.target.program, dep.origin)
        return _fanned(origin, index.fields_in(dep.target), dep.site, inward=True)
    return _copied(index, barrier, dep.target, dep.source, dep.site)


def _linked(index: LeafIndex, barrier: Barrier, link: LinkRow) -> tuple[_Moved, ...]:
    caller = byte_range(link.caller_extent, link.caller)
    callee = byte_range(link.callee_extent, link.callee)
    site = f"{link.caller}/{link.node}"
    entered = _copied(index, barrier, callee, caller, site)
    if not link.returns:
        return (entered,)
    return (entered, _copied(index, barrier, caller, callee, site))


def _edge(
    ends: tuple[str, str], flows: Iterable[Flow], programs: Mapping[str, str]
) -> GraphEdge:
    taken = tuple(flows)
    source, target = ends
    return GraphEdge(
        source=source,
        target=target,
        sites=len({flow.site for flow in taken}),
        clustered=any(flow.clustered for flow in taken),
        cross_program=programs[source] != programs[target],
    )


def _ends(flow: Flow) -> tuple[str, str]:
    return (flow.source, flow.target)


def field_graph(
    index: LeafIndex,
    deps: Sequence[DepRow],
    links: Sequence[LinkRow],
    barrier: Barrier,
) -> FieldGraph:
    moved = (
        *(_moved(index, barrier, dep) for dep in deps if dep.sink or dep.target.known),
        *(step for link in links for step in _linked(index, barrier, link)),
    )
    nodes = {node.id: node for found, _ in moved for node in found}
    flows = sorted(
        flow for _, found in moved for flow in found if flow.source != flow.target
    )
    programs = {node.id: node.program for node in nodes.values()}
    return FieldGraph(
        barrier=barrier.name,
        nodes=tuple(nodes[node] for node in sorted(nodes)),
        edges=tuple(
            _edge(ends, group, programs) for ends, group in groupby(flows, _ends)
        ),
    )
