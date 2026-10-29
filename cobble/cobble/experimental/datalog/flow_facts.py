"""Every value the fixpoint moved, with its typed origin, as facts."""

from pathlib import Path

from cobble.dataflow.fixpoint.flow_attrs import FlowAttrs
from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import required
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import GraphEdge

FP_FLOW = Relation(
    "fp_flow",
    (
        symbol("src"),
        symbol("dst"),
        symbol("n"),
        symbol("okind"),
        symbol("oname"),
        symbol("sext"),
        symbol("dext"),
    ),
)


def _flow(edge: GraphEdge) -> Row:
    attrs = FlowAttrs.model_validate(edge.attrs)
    return (
        edge.source,
        edge.target,
        attrs.node,
        str(attrs.origin.kind),
        attrs.origin.name,
        attrs.source_extent,
        attrs.target_extent,
    )


def flow_facts(run: Path) -> tuple[Facts, ...]:
    _, edges = read_graph(required(run / "fixpoint" / "graph.jsonl"))
    return (Facts(FP_FLOW, tuple(map(_flow, edges))),)
