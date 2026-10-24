"""cobble-experimental-aggregate-decompose: rounds of NMF over a paragraph x field matrix."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.decompose import rounds, write_rounds
from cobble.experimental.aggregates.matrix import load_matrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_step import RoundStep

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-decompose",
        description=(
            "Experimental: rounds of non-negative matrix factorization over a "
            "paragraph x field matrix; each round factors what earlier rounds leave "
            "unexplained."
        ),
    )
    parser.add_argument(
        "--matrix", type=Path, required=True, help="matrix.npz from the matrix stage"
    )
    parser.add_argument(
        "--meta", type=Path, required=True, help="meta.json from the matrix stage"
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        nargs="+",
        required=True,
        help="per round, strictly decreasing: fewest paragraphs a field is written in to enter it",
    )
    parser.add_argument(
        "--k", type=int, nargs="+", required=True, help="per round: its factor count"
    )
    parser.add_argument(
        "--max-iter", type=int, default=500, help="NMF max iterations (default 500)"
    )
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument("--out-dir", type=Path, required=True, help="output directory")
    return parser


def _steps(
    parser: argparse.ArgumentParser, arguments: argparse.Namespace
) -> tuple[RoundStep, ...]:
    thresholds: list[int] = arguments.min_occurrences
    counts: list[int] = arguments.k
    if len(thresholds) != len(counts):
        parser.error("--min-occurrences and --k need one value per round each")
    if any(later >= earlier for earlier, later in pairwise(thresholds)):
        parser.error("--min-occurrences must strictly decrease from round to round")
    return tuple(
        RoundStep(min_occurrences=threshold, k=k)
        for threshold, k in zip(thresholds, counts, strict=True)
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    parser = _parser()
    arguments = parser.parse_args(tuple(argv) if argv else None)
    steps = _steps(parser, arguments)
    logger.info("decompose: loading %s", arguments.matrix)
    loaded = load_matrix(arguments.matrix, arguments.meta)
    logger.info(
        "decompose: %d fields, %d non-zeros", len(loaded.fields), loaded.matrix.nnz
    )
    found = rounds(
        loaded,
        steps,
        NmfSettings(max_iter=arguments.max_iter, seed=arguments.seed),
    )
    write_rounds(arguments.out_dir, found)
    return 0
