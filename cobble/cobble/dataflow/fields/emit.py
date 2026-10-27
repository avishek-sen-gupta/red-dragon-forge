"""FIELD nodes, FLOWS_TO edges, and the two side tables, from one program's flow.

An edge carries its two byte ranges and the CFG node that moved them, and nothing
else. Not the guard condition: carrying it would multiply the lattice by the
number of distinct guard paths and would depend on the path-enumeration walk bead
red-dragon-forge-3ao found broken, so a reader wanting the condition asks srccfg
for the node's guards. Not the defining node either -- one source range at one
node commonly has several reaching definers, so that relation is a table of its
own and an edge that wants it joins on (node, source_extent).

What an edge cannot avoid restating is its endpoints' names. The graph model needs
node ids, and the id of a range is the smallest declared field covering it, so the
two ids are derived from the two ranges and the layout rather than being facts of
their own. That is the one denormalisation the model imposes; everything else
derivable was removed. Which OTHER fields a moved range touches, which children a
group write filled, whether byte k of the target came from byte k of the source --
all of it follows from the ranges plus the declared extents, published once per
field in their own artefact because where a field *is* is true whether or not a
value ever moved through it. See side_tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cobble.corpus_index import FileLocationResolver
from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.naming import smallest_covering
from cobble.dataflow.fields.program_layout import ProgramLayout
from cobble.dataflow.fields.side_tables import (
    DeclaredCell,
    DeclaredRecord,
    FieldExtents,
    ProgramSink,
    ReachingDefs,
)
from cobble.dataflow.fixpoint.fixpoint import FlowEdge, ProgramFlow
from cobble.knowledge_graph.graph_types import (
    AttrValue,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


@dataclass(frozen=True)
class ProgramRecords:
    """Everything one member contributes, split by the artefact it belongs in.

    Named fields rather than a tuple the caller unpacks positionally: the graph
    halves go to one sink and each side table to its own, and which is which
    should not depend on the reader remembering an order.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    extents: tuple[FieldExtents, ...]
    defs: tuple[ReachingDefs, ...]
    sinks: tuple[ProgramSink, ...] = ()


def field_id(program: str, name: str) -> str:
    """A field name is only unique within a program, so the id says which one."""
    return f"{program}.{name}".upper()


def _source_name(edge: FlowEdge, index: CellIndex) -> str:
    """An origin where there is one; a field name otherwise.

    ``origin`` is non-empty exactly when the extent is NOWHERE, whose own
    ``field_name`` is empty -- so this branch is what stops a synthetic source
    from being emitted as ``<program>.``.
    """
    if edge.origin:
        return edge.origin
    return smallest_covering(edge.source, index)


def _source_extent(edge: FlowEdge) -> str:
    return "" if edge.origin else extent_text(edge.source)


def _attrs(edge: FlowEdge) -> dict[str, AttrValue]:
    return {
        "node": edge.node,
        "source_extent": _source_extent(edge),
        "target_extent": extent_text(edge.target),
        "origin": edge.origin,
        "literal": edge.literal,
        "landing": list(edge.landing),
        "rebuilt": edge.rebuilt,
    }


def _edge(edge: FlowEdge, program: str, index: CellIndex) -> GraphEdge:
    return GraphEdge(
        source=field_id(program, _source_name(edge, index)),
        source_kind=NodeKind.FIELD,
        target=field_id(program, smallest_covering(edge.target, index)),
        target_kind=NodeKind.FIELD,
        kind=EdgeKind.FLOWS_TO,
        attrs=_attrs(edge),
    )


def graph_records(
    flow: ProgramFlow,
    layout: ProgramLayout,
    locations: FileLocationResolver,
) -> ProgramRecords:
    """One program's FLOWS_TO edges, a FIELD node per endpoint, every field's extents.

    The nodes stay derived from the edges: a field no value ever reaches and none
    ever leaves is a declaration, not a dataflow fact, and a node per declared
    field would put the whole of a member's storage into the graph -- roughly
    half again as many nodes as it has endpoints, on the member measured.

    The declarations still have to be published, because an edge names the
    smallest field covering the bytes it moved: a group-level write puts the
    group in the graph and leaves every child it filled out, and the child is
    what a reader is asking about. ``extents`` is how that reader gets it back,
    from its own file rather than from the graph.

    ``locations`` is asked even though every FIELD answer is the same constant.
    A node's location must come from the one resolver table or the reason it
    carries drifts from the reason GraphWriter would have given the same node,
    and a node built without asking is NOT_ATTEMPTED -- which would claim no
    index was in reach when one was.
    """
    index = layout.index
    edges = tuple(_edge(edge, flow.program, index) for edge in flow.edges)
    ids = tuple(
        dict.fromkeys(
            node_id for edge in edges for node_id in (edge.source, edge.target)
        )
    )
    return ProgramRecords(
        nodes=tuple(_node(node_id, locations) for node_id in ids),
        edges=edges,
        extents=_declared_extents(layout, flow.program),
        defs=_reaching_defs(flow),
        sinks=_sinks(flow),
    )


def _records_declared(layout: ProgramLayout) -> Mapping[str, DeclaredRecord]:
    """Each record's own three facts, under the name its cells carry.

    Found by name, because that is the handle a cell holds and the same handle
    ``CellIndex.placements`` is addressed by -- so a program whose two records
    share a name is already one this package cannot address, and this is not the
    place that starts.
    """
    return MappingProxyType(
        {
            record.name: DeclaredRecord(
                origin=record.origin, size=record.size, position=position
            )
            for position, record in enumerate(layout.records)
        }
    )


def _declared_extents(layout: ProgramLayout, program: str) -> tuple[FieldExtents, ...]:
    """Every declared name in the program, with how and where it was declared.

    Declared, not reached: the point of the file is the fields the graph does
    NOT mention, so a consumer can intersect a group write's extent against them
    and name the children it covered.

    Level and usage come off the first cell because every occurrence of one
    declaration shares both. A name two records declare at different levels keeps
    the first, which is the same tie ``smallest_covering`` already resolves one
    way for the ids in the graph -- and both levels are in ``cells`` either way,
    where a reader rebuilding the layout needs each cell's own.
    """
    index = layout.index
    declared = _records_declared(layout)
    return tuple(
        FieldExtents(
            id=field_id(program, name),
            level=cells[0].level,
            usage=cells[0].usage,
            extents=tuple(extent_text(index.extent_of(cell)) for cell in cells),
            program=program,
            cells=tuple(
                DeclaredCell(cell=cell, record=declared[cell.record]) for cell in cells
            ),
        )
        for name, cells in index.by_name.items()
    )


def _sinks(flow: ProgramFlow) -> tuple[ProgramSink, ...]:
    return tuple(
        ProgramSink(
            program=flow.program,
            node=sink.node,
            sink=sink.sink,
            source_extent=extent_text(sink.source),
            definers=sink.definers,
        )
        for sink in flow.sinks
    )


def _reaching_defs(flow: ProgramFlow) -> tuple[ReachingDefs, ...]:
    """The definitions reaching each read, in the wire form of their extents."""
    return tuple(
        ReachingDefs(
            program=flow.program,
            node=entry.node,
            extent=extent_text(entry.extent),
            definers=entry.definers,
            held=entry.held,
        )
        for entry in flow.defs
    )


def _node(node_id: str, locations: FileLocationResolver) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=NodeKind.FIELD,
        location=locations.resolve_file_path(NodeKind.FIELD, node_id),
    )
