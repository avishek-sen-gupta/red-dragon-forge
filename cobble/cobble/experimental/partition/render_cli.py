"""cobble-experimental-partition-render: the WebGL page of a field graph and its clusters."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import cobble.knowledge_graph
from cobble.cli_logging import configure_cli_logging
from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.page import page

logger = logging.getLogger(__name__)

VENDOR = Path(cobble.knowledge_graph.__file__).parent / "vendor"
SCRIPTS = (VENDOR / "graphology.umd.min.js", VENDOR / "sigma.min.js")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-render",
        description="Experimental: one self-contained WebGL page of a partition graph and its clusters.",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        required=True,
        help="the graph cobble-experimental-partition-graph wrote",
    )
    parser.add_argument(
        "--clusters",
        type=Path,
        required=True,
        help="the clusters cobble-experimental-partition-clusters wrote",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="the HTML page to write"
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    graph = FieldGraph.model_validate_json(arguments.graph.read_text(encoding="utf-8"))
    clusters = ClusterSet.model_validate_json(
        arguments.clusters.read_text(encoding="utf-8")
    )
    scripts = tuple(script.read_text(encoding="utf-8") for script in SCRIPTS)
    arguments.out.write_text(page(graph, clusters, scripts), encoding="utf-8")
    logger.info("partition render: %d nodes -> %s", len(graph.nodes), arguments.out)
    return 0
