"""cobble-experimental-aggregate-matrix: field x field PPMI matrix from paragraph co-occurrences."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.matrix import build_ppmi_matrix, save_matrix
from cobble.experimental.aggregates.unify import read_unified

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-matrix",
        description=(
            "Experimental: build a field x field Positive PMI matrix from paragraph-level "
            "field co-occurrences in the reaching-definitions output."
        ),
    )
    parser.add_argument("--defs", type=Path, required=True, help="defs.jsonl from cobble-dataflow-fixpoint")
    parser.add_argument("--unified", type=Path, default=None, help="unified.jsonl from the unify stage (optional)")
    parser.add_argument("--min-fields", type=int, default=3, help="minimum distinct fields per paragraph (default 3)")
    parser.add_argument("--min-occurrences", type=int, default=5, help="minimum paragraphs per field (default 5)")
    parser.add_argument("--min-cooccurrences", type=int, default=3, help="minimum pair co-occurrences for PPMI (default 3)")
    parser.add_argument("--out-matrix", type=Path, required=True, help="output matrix.npz")
    parser.add_argument("--out-meta", type=Path, required=True, help="output meta.json")
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    args = _parser().parse_args(tuple(argv) if argv else None)
    canonical_map = read_unified(args.unified) if args.unified else None
    matrix, field_list, para_list, stats = build_ppmi_matrix(
        args.defs,
        canonical_map=canonical_map,
        min_fields_per_para=args.min_fields,
        min_occurrences=args.min_occurrences,
        min_cooccurrences=args.min_cooccurrences,
    )
    save_matrix(matrix, field_list, para_list, stats, args.out_matrix, args.out_meta)
    logger.info(
        "aggregate matrix: %d x %d, %d non-zeros -> %s",
        matrix.shape[0], matrix.shape[1], matrix.nnz, args.out_matrix,
    )
    return 0
