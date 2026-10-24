"""Builds the field graph: each dep row and link mapped onto the elementary fields it moves."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from itertools import groupby, product
from operator import itemgetter

from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.trace_query import DepRow
from cobble.experimental.partition.barrier import Barrier
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.field_leaf import FieldLeaf
from cobble.experimental.partition.flow import Flow
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.leaf_index import LeafIndex
from cobble.experimental.partition.link_row import LinkRow
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.span import Span

_Moved = tuple[tuple[GraphNode, ...], tuple[Flow, ...]]
_Pair = tuple[FieldLeaf, FieldLeaf]
_Rows = Mapping[str, tuple[DepRow, ...]]


def field_node(leaf: FieldLeaf) -> GraphNode:
    return GraphNode(
        id=leaf.node,
        kind=NodeKind.FIELD,
        label=f"{leaf.program}.{leaf.occurrence}",
        program=leaf.program,
        record=leaf.record,
        pic=leaf.pic,
        field=leaf.name,
        subscripts=leaf.subscripts,
        size=leaf.end - leaf.start,
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


def _pairs(target: Span, source: Span) -> tuple[_Pair, ...]:
    if len(target.fields) == 1 or len(source.fields) == 1:
        return tuple((s, t) for s, t in product(source.fields, target.fields))
    return tuple(
        (s, t)
        for t in target.fields
        for start, end in (_aligned(target.range, source.range, t),)
        for s in source.fields
        if s.overlaps(start, end)
    )


def _span(index: LeafIndex, extent: ByteRange) -> Span:
    return Span(extent, index.fields_in(extent))


def _within(extent: ByteRange, start: int, end: int) -> ByteRange:
    return replace(extent, start=start, end=end)


def _covered(leaf: FieldLeaf, pieces: Sequence[FieldLeaf]) -> bool:
    return all(
        any(piece.start <= byte < piece.end for piece in pieces)
        for byte in range(leaf.start, leaf.end)
    )


def _distinct(leaves: Iterable[FieldLeaf]) -> tuple[FieldLeaf, ...]:
    return tuple({leaf: None for leaf in leaves})


def _traced(
    index: LeafIndex, rows: _Rows, extent: ByteRange, definers: Iterable[str]
) -> tuple[FieldLeaf, ...]:
    pieces = _distinct(
        piece
        for definer in definers
        for row in rows.get(definer, ())
        if (row.target.program, row.target.region) == (extent.program, extent.region)
        and extent.start <= row.target.start
        and row.target.end <= extent.end
        for piece in _through(index, rows, row)
    )
    kept = tuple(leaf for leaf in index.fields_in(extent) if not _covered(leaf, pieces))
    return _distinct((*kept, *pieces))


def _finer(
    index: LeafIndex, rows: _Rows, row: DepRow, leaf: FieldLeaf
) -> tuple[FieldLeaf, ...]:
    shift = row.source.start - row.target.start
    inner = _traced(
        index,
        {site: found for site, found in rows.items() if site != row.site},
        _within(row.source, leaf.start + shift, leaf.end + shift),
        row.definers,
    )
    if len(inner) < 2:
        return (leaf,)
    return tuple(
        replace(
            piece, region=leaf.region, start=piece.start - shift, end=piece.end - shift
        )
        for piece in inner
    )


def _through(index: LeafIndex, rows: _Rows, row: DepRow) -> tuple[FieldLeaf, ...]:
    written = index.fields_in(row.target)
    if not row.source.known:
        return written
    return tuple(piece for leaf in written for piece in _finer(index, rows, row, leaf))


def _read(index: LeafIndex, rows: _Rows, dep: DepRow) -> Span:
    return Span(dep.source, _traced(index, rows, dep.source, dep.definers))


def _placed(target: Span, source: Span, pair: _Pair) -> tuple[ByteAlignment, ...]:
    if not (target.range.exact and source.range.exact):
        return ()
    s, t = pair
    start, end = _aligned(target.range, source.range, t)
    low, high = max(start, s.start), min(end, s.end)
    if low >= high:
        return ()
    shift = source.range.start - target.range.start
    return (
        ByteAlignment(
            source=low - s.start, target=low - shift - t.start, length=high - low
        ),
    )


def _copied(barrier: Barrier, target: Span, source: Span, site: str) -> _Moved:
    pairs = _pairs(target, source)
    clustered = not barrier.blocks(set(pairs))
    return (
        tuple(field_node(leaf) for pair in pairs for leaf in pair),
        tuple(
            Flow(s.node, t.node, site, clustered, _placed(target, source, (s, t)))
            for s, t in pairs
        ),
    )


def _fanned(
    terminal: GraphNode, leaves: tuple[FieldLeaf, ...], site: str, *, inward: bool
) -> _Moved:
    return (
        (terminal, *(field_node(leaf) for leaf in leaves)),
        tuple(
            (
                Flow(terminal.id, leaf.node, site, True)
                if inward
                else Flow(leaf.node, terminal.id, site, True)
            )
            for leaf in leaves
        ),
    )


def _origin_name(dep: DepRow) -> str:
    return f"{dep.origin} {dep.literal}" if dep.literal else dep.origin


def _moved(index: LeafIndex, rows: _Rows, barrier: Barrier, dep: DepRow) -> _Moved:
    if dep.sink:
        sink = _terminal(NodeKind.SINK, dep.source.program, dep.sink)
        return _fanned(sink, _read(index, rows, dep).fields, dep.site, inward=False)
    if not dep.source.known:
        origin = _terminal(NodeKind.ORIGIN, dep.target.program, _origin_name(dep))
        return _fanned(origin, index.fields_in(dep.target), dep.site, inward=True)
    return _copied(barrier, _span(index, dep.target), _read(index, rows, dep), dep.site)


def _linked(index: LeafIndex, barrier: Barrier, link: LinkRow) -> tuple[_Moved, ...]:
    caller = byte_range(link.caller_extent, link.caller)
    callee = byte_range(link.callee_extent, link.callee)
    site = f"{link.caller}/{link.node}"
    caller_span, callee_span = _span(index, caller), _span(index, callee)
    entered = _copied(barrier, callee_span, caller_span, site)
    if not link.returns:
        return (entered,)
    return (entered, _copied(barrier, caller_span, callee_span, site))


def _edge(
    ends: tuple[str, str],
    flows: Iterable[Flow],
    programs: Mapping[str, str],
    barrier: str,
) -> GraphEdge:
    taken = tuple(flows)
    source, target = ends
    return GraphEdge(
        source=source,
        target=target,
        sites=len({flow.site for flow in taken}),
        clustered=any(flow.clustered for flow in taken),
        cross_program=programs[source] != programs[target],
        barrier=barrier,
        alignments=tuple(
            ByteAlignment(source=start, target=landing, length=length)
            for start, landing, length in sorted(
                {_placement(placed) for flow in taken for placed in flow.alignment}
            )
        ),
        aligned=all(flow.alignment for flow in taken),
    )


def _placement(placed: ByteAlignment) -> tuple[int, int, int]:
    return (placed.source, placed.target, placed.length)


def _ends(flow: Flow) -> tuple[str, str]:
    return (flow.source, flow.target)


def _rows(deps: Sequence[DepRow]) -> _Rows:
    written = sorted(
        (dep.site, i) for i, dep in enumerate(deps) if dep.target.known and not dep.sink
    )
    return {
        site: tuple(deps[i] for _, i in group)
        for site, group in groupby(written, itemgetter(0))
    }


def field_graph(
    index: LeafIndex,
    deps: Sequence[DepRow],
    links: Sequence[LinkRow],
    barrier: Barrier,
) -> FieldGraph:
    rows = _rows(deps)
    moved = (
        *(
            _moved(index, rows, barrier, dep)
            for dep in counted(deps, "dep rows mapped", len(deps))
            if dep.sink or dep.target.known
        ),
        *(
            step
            for link in counted(links, "links mapped", len(links))
            for step in _linked(index, barrier, link)
        ),
    )
    nodes = {node.id: node for found, _ in moved for node in found}
    flows = sorted(
        flow for _, found in moved for flow in found if flow.source != flow.target
    )
    programs = {node.id: node.program for node in nodes.values()}
    return FieldGraph(
        nodes=tuple(nodes[node] for node in sorted(nodes)),
        edges=tuple(
            _edge(ends, group, programs, barrier.name)
            for ends, group in groupby(flows, _ends)
        ),
    )
