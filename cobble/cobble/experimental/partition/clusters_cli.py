"""cobble-experimental-partition-clusters: the clusters of a field graph, and a report on them."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.partition.cluster_file import write_clusters
from cobble.experimental.partition.cluster_report import cluster_report
from cobble.experimental.partition.clustering import cluster_set
from cobble.experimental.partition.graph_file import read_graph

logger = logging.getLogger(__name__)

DEFAULT_SPLIT_AT = 30


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-clusters",
        description="Experimental: clusters of fields inside each program of a partition graph.",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        required=True,
        help="the graph cobble-experimental-partition-graph wrote",
    )
    parser.add_argument(
        "--split-at",
        type=int,
        default=DEFAULT_SPLIT_AT,
        help="components of at least this many fields are split into Louvain communities",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="the clusters JSONL to write"
    )
    parser.add_argument(
        "--report", type=Path, required=True, help="the markdown report to write"
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    logger.info("partition clusters: reading %s", arguments.graph)
    graph = read_graph(arguments.graph)
    logger.info(
        "partition clusters: %d nodes, %d edges", len(graph.nodes), len(graph.edges)
    )
    clusters = cluster_set(graph, arguments.split_at)
    write_clusters(arguments.out, clusters)
    arguments.report.write_text(cluster_report(graph, clusters), encoding="utf-8")
    logger.info(
        "partition clusters: %d clusters, %d isolated fields -> %s, %s",
        len(clusters.clusters),
        len(clusters.isolated),
        arguments.out,
        arguments.report,
    )
    return 0
