"""The knowledge graph's nodes and edges as facts."""

from pathlib import Path

from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import required
from cobble.knowledge_graph.graph_file import read_graph

KG_NODE = Relation("kg_node", (symbol("id"), symbol("kind")))
KG_EDGE = Relation("kg_edge", (symbol("src"), symbol("kind"), symbol("dst")))


def knowledge_facts(run: Path) -> tuple[Facts, ...]:
    nodes, edges = read_graph(required(run / "knowledge-graph.jsonl"))
    return (
        Facts(KG_NODE, tuple((node.id, node.kind.value) for node in nodes)),
        Facts(
            KG_EDGE,
            tuple((edge.source, edge.kind.value, edge.target) for edge in edges),
        ),
    )
