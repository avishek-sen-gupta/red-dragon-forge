"""cobble-experimental-partition-graph: the field graph of every trace in a directory."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.trace_query import DepRow, load
from cobble.experimental.partition.barrier_kind import BarrierKind
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.graph_build import field_graph
from cobble.experimental.partition.graph_file import write_graph
from cobble.experimental.partition.leaf_index import LeafIndex, leaf_index
from cobble.experimental.partition.link_row import LinkRow
from cobble.experimental.partition.progress import counted

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
        "--out", type=Path, required=True, help="the graph JSONL to write"
    )
    return parser


def _deps(traces: Sequence[Path]) -> tuple[DepRow, ...]:
    return tuple(
        dep
        for trace in counted(traces, "traces read", len(traces))
        for dep in load(trace)
    )


def _links(path: Path) -> tuple[LinkRow, ...]:
    if path == Path():
        return ()
    return tuple(LinkRow.model_validate_json(line) for line in _lines(path))


def _index(path: Path) -> LeafIndex:
    extents = _lines(path)
    return leaf_index(
        ExtentRow.model_validate_json(line)
        for line in counted(extents, "extent rows indexed", len(extents))
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    traces = tuple(sorted(arguments.traces.glob("*.jsonl")))
    deps = _deps(traces)
    links = _links(arguments.links)
    barrier = arguments.barrier.barrier(arguments.fanout_limit)
    graph = field_graph(_index(arguments.extents), deps, links, barrier)
    logger.info("partition graph: writing %s", arguments.out)
    write_graph(arguments.out, graph)
    logger.info(
        "partition graph: %d traces, %d dep rows, %d links -> %d nodes, %d edges (%d blocked by %s) in %s",
        len(traces),
        len(deps),
        len(links),
        len(graph.nodes),
        len(graph.edges),
        sum(1 for edge in graph.edges if not edge.clustered),
        barrier.name,
        arguments.out,
    )
    return 0
