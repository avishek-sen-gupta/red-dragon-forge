"""Dataset slots: every layout a dataset is read or written with cuts its record, and each field links to the slots its bytes cover."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import groupby, pairwise

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.experimental.partition.byte_alignment import ByteAlignment
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.dataset_flow import DatasetFlow
from cobble.experimental.partition.dataset_site import DatasetSite
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.field_leaf import FieldLeaf
from cobble.experimental.partition.graph_build import field_node
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.leaf_index import LeafIndex
from cobble.experimental.partition.node_kind import NodeKind

CLAMPED = "clamped"
OVERLAPPING = "overlapping-layouts"

_Interval = tuple[int, int]
_Placed = tuple[tuple[FieldLeaf, _Interval], ...]
_Slot = tuple[str, _Interval]


def _length(record: ByteRange) -> int:
    return record.end - record.start


def _placed(index: LeafIndex, site: DatasetSite) -> _Placed:
    record = site.use.record
    return tuple(
        (
            leaf,
            (
                max(leaf.start, record.start) - record.start,
                min(leaf.end, record.end) - record.start,
            ),
        )
        for leaf in index.fields_in(record)
    )


def _overlap(left: _Interval, right: _Interval) -> _Interval:
    return (max(left[0], right[0]), min(left[1], right[1]))


def _meets(left: _Interval, right: _Interval) -> bool:
    low, high = _overlap(left, right)
    return low < high


def _cuts(index: LeafIndex, sites: Sequence[DatasetSite]) -> tuple[_Interval, ...]:
    bounds = sorted(
        {
            0,
            *(_length(site.use.record) for site in sites),
            *(
                end
                for site in sites
                for _, span in _placed(index, site)
                for end in span
            ),
        }
    )
    return tuple(pairwise(bounds))


def _slots(
    index: LeafIndex, identity: str, sites: Sequence[DatasetSite]
) -> tuple[_Slot, ...]:
    return tuple(
        (f"{identity}[{low}:{high}]", (low, high)) for low, high in _cuts(index, sites)
    )


def _crossed(
    span: _Interval, leaf: FieldLeaf, placed: _Placed, slot: _Interval
) -> bool:
    inside = _overlap(span, slot)
    return any(
        other != leaf and _meets(inside, other_span) for other, other_span in placed
    )


def _reasons(site: DatasetSite, crossed: bool) -> tuple[str, ...]:
    return (
        *site.reasons,
        *(() if site.use.record.exact else (CLAMPED,)),
        *((OVERLAPPING,) if crossed else ()),
    )


def _alignment(
    origin: int, span: _Interval, slot: _Interval, writes: bool
) -> ByteAlignment:
    low, high = _overlap(span, slot)
    in_field, in_slot = low - origin, low - slot[0]
    if writes:
        return ByteAlignment(source=in_field, target=in_slot, length=high - low)
    return ByteAlignment(source=in_slot, target=in_field, length=high - low)


def _flow(
    site: DatasetSite, slot: _Slot, held: tuple[FieldLeaf, _Interval], placed: _Placed
) -> DatasetFlow:
    leaf, span = held
    name, bytes_ = slot
    reasons = _reasons(site, _crossed(span, leaf, placed, bytes_))
    ends = (leaf.node, name) if site.use.writes else (name, leaf.node)
    origin = leaf.start - site.use.record.start
    return DatasetFlow(
        source=ends[0],
        target=ends[1],
        site=site.use.site,
        certainty=Certainty.POSSIBLE if reasons else Certainty.EXACT,
        reasons=reasons,
        alignment=(
            () if reasons else (_alignment(origin, span, bytes_, site.use.writes),)
        ),
    )


def _flows(
    index: LeafIndex, site: DatasetSite, slots: Sequence[_Slot]
) -> tuple[DatasetFlow, ...]:
    placed = _placed(index, site)
    return tuple(
        _flow(site, slot, (leaf, span), placed)
        for slot in slots
        for leaf, span in placed
        if _meets(span, slot[1])
    )


def _slot_node(slot: _Slot, label: str, identity: str) -> GraphNode:
    name, (low, high) = slot
    return GraphNode(
        id=name,
        kind=NodeKind.DATASET,
        label=label,
        program="",
        record=identity,
        size=high - low,
        offset=low,
    )


def _unresolved(
    index: LeafIndex, site: DatasetSite
) -> tuple[tuple[GraphNode, ...], tuple[DatasetFlow, ...]]:
    slot = (f"{site.use.site}|{site.identity}", (0, _length(site.use.record)))
    return (_slot_node(slot, site.identity, site.identity),), _flows(
        index, site, (slot,)
    )


def _dataset(
    index: LeafIndex, identity: str, sites: Sequence[DatasetSite]
) -> tuple[tuple[GraphNode, ...], tuple[DatasetFlow, ...]]:
    slots = _slots(index, identity, sites)
    return (
        tuple(_slot_node(slot, slot[0], identity) for slot in slots),
        tuple(flow for site in sites for flow in _flows(index, site, slots)),
    )


def _edge(
    ends: tuple[str, str], flows: Sequence[DatasetFlow], barrier: str
) -> GraphEdge:
    exact = all(flow.certainty is Certainty.EXACT for flow in flows)
    return GraphEdge(
        source=ends[0],
        target=ends[1],
        sites=len({flow.site for flow in flows}),
        clustered=False,
        cross_program=True,
        barrier=barrier,
        alignments=tuple(
            ByteAlignment(source=start, target=landing, length=length)
            for start, landing, length in sorted(
                {
                    (placed.source, placed.target, placed.length)
                    for flow in flows
                    for placed in flow.alignment
                }
            )
        ),
        aligned=all(flow.alignment for flow in flows),
        certainty=Certainty.EXACT if exact else Certainty.POSSIBLE,
        reasons=tuple(
            dict.fromkeys(reason for flow in flows for reason in flow.reasons)
        ),
    )


def _ends(flow: DatasetFlow) -> tuple[str, str]:
    return (flow.source, flow.target)


def _by_identity(
    sites: Sequence[DatasetSite],
) -> tuple[tuple[str, tuple[DatasetSite, ...]], ...]:
    resolved = tuple(site for site in sites if site.resolved)
    return tuple(
        (name, tuple(site for site in resolved if site.identity == name))
        for name in sorted({site.identity for site in resolved})
    )


def _ordered(edges: Sequence[GraphEdge]) -> tuple[GraphEdge, ...]:
    ranked = sorted((edge.source, edge.target, i) for i, edge in enumerate(edges))
    return tuple(edges[rank[2]] for rank in ranked)


def with_datasets(
    graph: FieldGraph, index: LeafIndex, sites: Sequence[DatasetSite]
) -> FieldGraph:
    parts = (
        *(_dataset(index, name, group) for name, group in _by_identity(sites)),
        *(_unresolved(index, site) for site in sites if not site.resolved),
    )
    flows = sorted(flow for _, found in parts for flow in found)
    leaves = {
        leaf.node: field_node(leaf)
        for site in sites
        for leaf, _ in _placed(index, site)
    }
    nodes = {
        **leaves,
        **{node.id: node for found, _ in parts for node in found},
        **{node.id: node for node in graph.nodes},
    }
    barrier = graph.barrier
    edges = (
        *graph.edges,
        *(_edge(ends, tuple(group), barrier) for ends, group in groupby(flows, _ends)),
    )
    return FieldGraph(
        nodes=tuple(nodes[name] for name in sorted(nodes)),
        edges=_ordered(edges),
    )
