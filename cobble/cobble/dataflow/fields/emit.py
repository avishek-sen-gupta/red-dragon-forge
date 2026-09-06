"""FIELD nodes and FLOWS_TO edges from one program's flow.

An edge carries its two extents and the CFG node id that wrote them, and not
the guard condition -- a reader wanting the condition asks srccfg for that
node's guards. Carrying it would multiply the lattice by the number of distinct
guard paths and would depend on the path-enumeration walk bead
red-dragon-forge-3ao found broken.

Expansion -- one attribute naming every aliasing view of an extent -- is opt-in
for the same reason naming lives outside the lattice: a record and its REDEFINES
views multiply the names of one byte range without adding a fact about flow.
"""

from __future__ import annotations

from cobble.corpus_index import FileLocationResolver
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.fixpoint import FlowEdge, ProgramFlow
from cobble.dataflow.fields.naming import covering_fields, smallest_covering
from cobble.knowledge_graph.graph_types import (
    AttrValue,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def field_id(program: str, name: str) -> str:
    """A field name is only unique within a program, so the id says which one."""
    return f"{program}.{name}".upper()


def _source_name(edge: FlowEdge, index: CellIndex) -> str:
    """An origin where there is one; a field name otherwise.

    ``origin`` is non-empty exactly when the extent is NOWHERE, whose own
    ``field_name`` is empty -- so this branch is what stops a synthetic source
    from being emitted as ``<program>.``.
    """
    if edge.source.origin:
        return edge.source.origin
    return smallest_covering(edge.source.extent, index)


def _source_extent(edge: FlowEdge) -> str:
    return "" if edge.source.origin else str(edge.source.extent)


def _expansion(edge: FlowEdge, index: CellIndex, expand: bool) -> dict[str, AttrValue]:
    if not expand:
        return {}
    return {
        "target_fields": ",".join(covering_fields(edge.target, index)),
        "source_fields": ",".join(covering_fields(edge.source.extent, index)),
    }


def _attrs(edge: FlowEdge, index: CellIndex, expand: bool) -> dict[str, AttrValue]:
    return {
        "node": edge.node,
        "source_extent": _source_extent(edge),
        "target_extent": str(edge.target),
        **_expansion(edge, index, expand),
    }


def _edge(edge: FlowEdge, program: str, index: CellIndex, expand: bool) -> GraphEdge:
    return GraphEdge(
        source=field_id(program, _source_name(edge, index)),
        source_kind=NodeKind.FIELD,
        target=field_id(program, smallest_covering(edge.target, index)),
        target_kind=NodeKind.FIELD,
        kind=EdgeKind.FLOWS_TO,
        attrs=_attrs(edge, index, expand),
    )


def graph_records(
    flow: ProgramFlow,
    index: CellIndex,
    expand: bool,
    locations: FileLocationResolver,
) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
    """Every FLOWS_TO edge of one program, with a FIELD node per endpoint.

    The nodes are derived from the edges rather than from the program's fields:
    a field no value ever reaches and none ever leaves is a declaration, not a
    dataflow fact, and emitting one node per declared field would put the
    corpus's whole 5.6M-cell expansion into the graph.

    ``locations`` is asked even though every FIELD answer is the same constant.
    A node's location must come from the one resolver table or the reason it
    carries drifts from the reason GraphWriter would have given the same node,
    and a node built without asking is NOT_ATTEMPTED -- which would claim no
    index was in reach when one was.
    """
    edges = tuple(_edge(edge, flow.program, index, expand) for edge in flow.edges)
    ids = tuple(
        dict.fromkeys(
            node_id for edge in edges for node_id in (edge.source, edge.target)
        )
    )
    return tuple(_node(node_id, locations) for node_id in ids), edges


def _node(node_id: str, locations: FileLocationResolver) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=NodeKind.FIELD,
        location=locations.resolve_file_path(NodeKind.FIELD, node_id),
    )
