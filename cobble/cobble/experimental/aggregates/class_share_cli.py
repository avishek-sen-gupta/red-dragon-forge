"""cobble-experimental-aggregate-class-share: how much of the matrix the unified classes hold, per decompose threshold."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.class_share import class_shares
from cobble.experimental.aggregates.matrix import load_matrix
from cobble.experimental.aggregates.unify import read_unified

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-class-share",
        description=(
            "Experimental: per threshold, the columns decompose would factor, how many "
            "are unified classes, and the classes' share of those columns' entries."
        ),
    )
    parser.add_argument(
        "--matrix", type=Path, required=True, help="matrix.npz from the matrix stage"
    )
    parser.add_argument(
        "--meta", type=Path, required=True, help="meta.json from the matrix stage"
    )
    parser.add_argument(
        "--unified",
        type=Path,
        required=True,
        help="unified.jsonl from cobble-experimental-aggregate-unify",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        nargs="+",
        required=True,
        help="thresholds to report, as decompose takes them",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    found = load_matrix(arguments.matrix, arguments.meta)
    classes = frozenset(read_unified(arguments.unified).values())
    logger.info(
        "aggregate class share: %d fields, %d classes", len(found.fields), len(classes)
    )
    thresholds: list[int] = arguments.min_occurrences
    for found_share in class_shares(found, classes, thresholds):
        logger.info(
            "aggregate class share: min-occurrences %d: %d columns, %d class columns, "
            "%.1f%% of their entries in class columns",
            found_share.min_occurrences,
            found_share.columns,
            found_share.class_columns,
            100 * found_share.share,
        )
    return 0
