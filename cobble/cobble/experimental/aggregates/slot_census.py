"""Counts the fields the graph's dataset slots link by why each did or did not join a class."""

from __future__ import annotations

from collections.abc import Set

from cobble.experimental.aggregates.byte_edge import ByteEdge
from cobble.experimental.aggregates.byte_graph import ByteGraph
from cobble.experimental.aggregates.exact_merge import unplaced_fields
from cobble.experimental.aggregates.slot_fields import SlotFields
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.node_kind import NodeKind


def _field_end(edge: ByteEdge, slots: Set[str], fields: Set[str]) -> frozenset[str]:
    ends = {edge.source, edge.target}
    if not ends & slots:
        return frozenset()
    return frozenset(ends & fields)


def _linked(
    graph: ByteGraph, slots: Set[str], fields: Set[str], exact: bool
) -> frozenset[str]:
    return frozenset(
        field
        for edge in graph.edges
        if (edge.certainty is Certainty.EXACT and edge.aligned) == exact
        for field in _field_end(edge, slots, fields)
    )


def slot_census(graph: ByteGraph, members: Set[str]) -> SlotFields:
    fields = {node.id: node for node in graph.nodes if node.kind is NodeKind.FIELD}
    slots = frozenset(node.id for node in graph.nodes if node.kind is NodeKind.DATASET)
    dataset = tuple(
        edge for edge in graph.edges if edge.source in slots or edge.target in slots
    )
    named = frozenset(fields)
    exact = _linked(graph, slots, named, exact=True)
    blocked = exact & unplaced_fields(graph, fields)
    return SlotFields(
        fields=len(fields),
        slots=len(slots),
        exact_edges=sum(1 for edge in dataset if edge.certainty is Certainty.EXACT),
        possible_edges=sum(
            1 for edge in dataset if edge.certainty is Certainty.POSSIBLE
        ),
        linked=len(exact),
        classed=len(exact & members),
        blocked=len(blocked),
        possible_only=len(_linked(graph, slots, named, exact=False) - exact),
    )
