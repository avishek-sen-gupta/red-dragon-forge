"""Small partition graphs the render tests share: three programs, a sink and one dataset slot."""

from __future__ import annotations

from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind


def edge(source: str, target: str, *, clustered: bool = True) -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        sites=2,
        clustered=clustered,
        cross_program=False,
        barrier="fanout-8",
    )


def program_field(program: str, name: str) -> GraphNode:
    return GraphNode(
        id=f"{program}:REC.{name}",
        kind=NodeKind.FIELD,
        label=f"{program}.{name}",
        program=program,
        record="REC",
    )


SPREAD_OUT = FieldGraph(
    nodes=(
        *(program_field("P", name) for name in "ABCDEFGH"),
        GraphNode(id="P|sink|MAP:M", kind=NodeKind.SINK, label="P MAP:M", program="P"),
        *(program_field("Q", name) for name in "ABCDEF"),
        *(program_field("S", name) for name in "AB"),
        GraphNode(
            id="DS[0:4]",
            kind=NodeKind.DATASET,
            label="DS[0:4]",
            program="",
            record="DS",
            size=4,
        ),
    ),
    edges=(
        *(edge(f"P:REC.{a}", f"P:REC.{b}") for a, b in ("AB", "BC", "CD", "EF")),
        edge("P:REC.D", "P|sink|MAP:M"),
        edge("P:REC.E", "P|sink|MAP:M"),
        edge("P:REC.G", "P|sink|MAP:M"),
        *(edge(f"Q:REC.{a}", f"Q:REC.{b}") for a, b in ("AB", "BC")),
        edge("S:REC.A", "S:REC.B"),
        edge("P:REC.A", "DS[0:4]", clustered=False),
        edge("DS[0:4]", "Q:REC.A", clustered=False),
    ),
)

LINKED = FieldGraph(
    nodes=SPREAD_OUT.nodes,
    edges=(*SPREAD_OUT.edges, edge("Q:REC.B", "S:REC.A", clustered=False)),
)
