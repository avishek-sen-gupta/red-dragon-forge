"""cobble-experimental-aggregate-decompose: NMF decomposition of a field PPMI matrix."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.decompose import nmf_sweep, write_results
from cobble.experimental.aggregates.matrix import load_matrix

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-decompose",
        description=(
            "Experimental: decompose a field x field PPMI matrix into domain aggregate "
            "candidates via non-negative matrix factorization."
        ),
    )
    parser.add_argument("--matrix", type=Path, required=True, help="matrix.npz from the matrix stage")
    parser.add_argument("--meta", type=Path, required=True, help="meta.json from the matrix stage")
    parser.add_argument("--k", type=str, default="10,15,20,25,30", help="comma-separated k values (default '10,15,20,25,30')")
    parser.add_argument("--max-iter", type=int, default=500, help="NMF max iterations (default 500)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument("--out-dir", type=Path, required=True, help="output directory")
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    args = _parser().parse_args(tuple(argv) if argv else None)
    k_values = [int(x.strip()) for x in args.k.split(",")]
    matrix, field_list, _meta = load_matrix(args.matrix, args.meta)
    results = nmf_sweep(matrix, field_list, k_values, args.max_iter, args.seed)
    write_results(args.out_dir, results)
    return 0
