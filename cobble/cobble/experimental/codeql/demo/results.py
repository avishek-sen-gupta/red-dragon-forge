"""The demo pack's result files, decoded by `codeql bqrs decode --format=json`, read into rows."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from cobble.experimental.codeql.demo.demo_results import DemoResults
from cobble.experimental.codeql.demo.drawn_edge import DrawnEdge
from cobble.experimental.codeql.demo.drawn_kind import DrawnKind
from cobble.experimental.codeql.demo.edge_row import EdgeRow
from cobble.experimental.codeql.demo.node_row import NodeRow
from cobble.experimental.codeql.demo.result_set import ResultSet
from cobble.experimental.codeql.demo.step_row import StepRow

FLOW_QUERIES: Mapping[str, DrawnEdge] = MappingProxyType(
    {
        "ReadToWriteSteps": DrawnEdge.READ_TO_WRITE,
        "ReadToDisplaySteps": DrawnEdge.READ_TO_DISPLAY,
    }
)


def _tuples(directory: Path, query: str) -> tuple[tuple[str, ...], ...]:
    text = (directory / f"{query}.json").read_text(encoding="utf-8")
    return ResultSet.model_validate_json(text).select.tuples


def _node(row: tuple[str, ...]) -> NodeRow:
    program, node, kind, label = row
    return NodeRow(program, node, DrawnKind(kind), label)


def _edge(row: tuple[str, ...]) -> EdgeRow:
    program, source, target, kind = row
    return EdgeRow(program, source, target, DrawnEdge(kind))


def _step(row: tuple[str, ...]) -> StepRow:
    program, source, target = row
    return StepRow(program, source, target)


def load_results(directory: Path) -> DemoResults:
    return DemoResults(
        nodes=tuple(map(_node, _tuples(directory, "CfgNodes"))),
        edges=tuple(map(_edge, _tuples(directory, "CfgEdges"))),
        flows=MappingProxyType(
            {
                kind: tuple(map(_step, _tuples(directory, query)))
                for query, kind in FLOW_QUERIES.items()
            }
        ),
    )
