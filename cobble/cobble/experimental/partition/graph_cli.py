"""cobble-experimental-partition-graph: the field graph of every trace in a directory."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.trace_query import load
from cobble.experimental.partition.barrier_kind import BarrierKind
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.graph_build import field_graph
from cobble.experimental.partition.leaf_index import leaf_index
from cobble.experimental.partition.link_row import LinkRow

logger = logging.getLogger(__name__)

DEFAULT_FANOUT_LIMIT = 8


def _lines(path: Path) -> tuple[str, ...]:
    return tuple(
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-graph",
        description="Experimental: the field graph of every cobble-fields-trace output in a directory.",
    )
    parser.add_argument(
        "--extents", type=Path, required=True, help="extents.jsonl from cobble-extents"
    )
    parser.add_argument(
        "--traces",
        type=Path,
        required=True,
        help="a directory of cobble-fields-trace JSONL files",
    )
    parser.add_argument(
        "--links",
        type=Path,
        default=Path(),
        help="links.jsonl from cobble-dataflow-combine",
    )
    parser.add_argument(
        "--barrier",
        type=BarrierKind,
        choices=tuple(BarrierKind),
        default=BarrierKind.FANOUT,
    )
    parser.add_argument(
        "--fanout-limit",
        type=int,
        default=DEFAULT_FANOUT_LIMIT,
        help="partners one field may have in one statement before the fanout barrier blocks it",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="the graph JSON to write"
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    traces = tuple(sorted(arguments.traces.glob("*.jsonl")))
    deps = tuple(dep for trace in traces for dep in load(trace))
    links = (
        tuple(LinkRow.model_validate_json(line) for line in _lines(arguments.links))
        if arguments.links != Path()
        else ()
    )
    index = leaf_index(
        ExtentRow.model_validate_json(line) for line in _lines(arguments.extents)
    )
    graph = field_graph(
        index, deps, links, arguments.barrier.barrier(arguments.fanout_limit)
    )
    arguments.out.write_text(graph.model_dump_json(), encoding="utf-8")
    logger.info(
        "partition graph: %d traces, %d dep rows, %d links -> %d nodes, %d edges (%d blocked by %s) in %s",
        len(traces),
        len(deps),
        len(links),
        len(graph.nodes),
        len(graph.edges),
        sum(1 for edge in graph.edges if not edge.clustered),
        graph.barrier,
        arguments.out,
    )
    return 0
