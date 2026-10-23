"""cobble-experimental-aggregate-unify: the fields of different programs the partition graph shows holding one datum."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.exact_merge import exact_classes
from cobble.experimental.aggregates.unify import write_unified
from cobble.experimental.partition.graph_file import read_graph

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-unify",
        description=(
            "Experimental: classes of fields in different programs whose every byte "
            "the partition graph moves, in place, onto each other."
        ),
    )
    parser.add_argument(
        "--graph",
        type=Path,
        required=True,
        help="graph.jsonl from cobble-experimental-partition-graph",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="unified.jsonl: one line per class",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    classes = exact_classes(read_graph(arguments.graph))
    write_unified(arguments.out, classes)
    logger.info("aggregate unify: %d classes -> %s", len(classes), arguments.out)
    return 0
