"""The name-level dependency graph's edges as facts."""

from pathlib import Path

from cobble.dataflow.depgraph.edge_line import EdgeLine
from cobble.experimental.datalog.column import number, symbol
from cobble.experimental.datalog.facts import Facts
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import lines

DEP_EDGE = Relation(
    "dep_edge",
    (
        symbol("src"),
        symbol("dst"),
        symbol("p"),
        number("seq"),
        symbol("verb"),
    ),
)


def dep_facts(run: Path) -> tuple[Facts, ...]:
    edges = tuple(
        EdgeLine.model_validate_json(line)
        for line in lines(run / "depgraph" / "edges.jsonl")
    )
    return (
        Facts(
            DEP_EDGE,
            tuple(
                (edge.src, edge.dst, edge.program, edge.seq, edge.verb)
                for edge in edges
            ),
        ),
    )
