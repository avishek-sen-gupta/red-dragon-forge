"""The partition graph's slots, origins, edges and byte alignments as facts."""

from pathlib import Path

from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.encoding import yes_no
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import required
from cobble.experimental.partition.graph_edge import GraphEdge
from cobble.experimental.partition.graph_file import read_graph
from cobble.experimental.partition.graph_node import GraphNode
from cobble.experimental.partition.node_kind import NodeKind

NO_BARRIER = "none"
SLOT = Relation(
    "slot",
    (
        symbol("id"),
        symbol("kind"),
        symbol("p"),
        symbol("record"),
        symbol("field"),
        number("off"),
        number("size"),
    ),
)
ORIGIN = Relation("origin", (symbol("id"), symbol("p"), symbol("kind"), symbol("name")))
SLOT_EDGE = Relation(
    "slot_edge",
    (
        symbol("src"),
        symbol("dst"),
        symbol("certainty"),
        symbol("cross"),
        symbol("barrier"),
    ),
)
SLOT_ALIGN = Relation(
    "slot_align",
    (
        symbol("src"),
        symbol("dst"),
        number("so"),
        number("to"),
        number("len"),
    ),
)


def _slot(node: GraphNode) -> Row:
    return (
        node.id,
        str(node.kind),
        node.program,
        node.record,
        node.field,
        node.offset,
        node.size,
    )


def _origin(node: GraphNode) -> Row:
    return (node.id, node.program, str(node.origin.kind), node.origin.name)


def _edge(edge: GraphEdge) -> Row:
    return (
        edge.source,
        edge.target,
        str(edge.certainty),
        yes_no(edge.cross_program),
        edge.barrier if edge.barrier else NO_BARRIER,
    )


def _alignments(edge: GraphEdge) -> tuple[Row, ...]:
    return tuple(
        (edge.source, edge.target, one.source, one.target, one.length)
        for one in edge.alignments
    )


def slot_facts(run: Path) -> tuple[Facts, ...]:
    graph = read_graph(required(run / "graph.jsonl"))
    return (
        Facts(SLOT, tuple(map(_slot, graph.nodes))),
        Facts(
            ORIGIN,
            tuple(
                _origin(node) for node in graph.nodes if node.kind is NodeKind.ORIGIN
            ),
        ),
        Facts(SLOT_EDGE, tuple(map(_edge, graph.edges))),
        Facts(
            SLOT_ALIGN,
            tuple(row for edge in graph.edges for row in _alignments(edge)),
        ),
    )
