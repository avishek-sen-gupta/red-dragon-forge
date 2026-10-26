"""cobble-experimental-aggregate-scorecard: held-out accuracy and the other axes of quality of each decompose round."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.decompose_cli import steps_of
from cobble.experimental.aggregates.matrix import load_matrix
from cobble.experimental.aggregates.nmf_settings import NmfSettings
from cobble.experimental.aggregates.round_score import RoundScore
from cobble.experimental.aggregates.scorecard import round_scores
from cobble.experimental.aggregates.unify import read_unified

logger = logging.getLogger(__name__)

STAGE = "aggregate scorecard"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-scorecard",
        description=(
            "Experimental: runs decompose's rounds and scores each on held-out AUC, "
            "fidelity, coverage, stability, distinctness, focus, cross-program reach "
            "and class share."
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
        help="per round, as decompose takes them",
    )
    parser.add_argument(
        "--k",
        type=int,
        nargs="+",
        required=True,
        help="per round, as decompose takes them",
    )
    parser.add_argument(
        "--max-iter", type=int, default=500, help="NMF max iterations (default 500)"
    )
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    return parser


def _logged(number: int, score: RoundScore) -> None:
    logger.info(
        "%s: round %d (min-occurrences %d, k=%d): held-out AUC %.3f",
        STAGE,
        number,
        score.min_occurrences,
        score.k,
        score.auc,
    )
    logger.info(
        "%s: round %d: fidelity %.3f relative error, coverage %.1f%%, "
        "stability %.3f, distinctness %.3f, focus %.3f, "
        "reach %.1f%% of factors across programs (median %.1f programs), "
        "class share %.1f%%",
        STAGE,
        number,
        score.fidelity,
        100 * score.coverage,
        score.stability,
        score.distinctness,
        score.focus,
        100 * score.reach,
        score.programs,
        100 * score.class_share,
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    parser = _parser()
    arguments = parser.parse_args(tuple(argv) if argv else None)
    steps = steps_of(parser, arguments)
    logger.info("%s: loading %s", STAGE, arguments.matrix)
    scores = round_scores(
        load_matrix(arguments.matrix, arguments.meta),
        steps,
        NmfSettings(max_iter=arguments.max_iter, seed=arguments.seed),
        read_unified(arguments.unified),
    )
    for number, score in enumerate(scores, 1):
        _logged(number, score)
    return 0
