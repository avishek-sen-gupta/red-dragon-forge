"""cobble-experimental-aggregate-matrix: field x field PPMI matrix from paragraph co-occurrences."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.def_line import DefLine
from cobble.experimental.aggregates.matrix import (
    MatrixLimits,
    paragraph_fields,
    ppmi_matrix,
    save_matrix,
)
from cobble.experimental.aggregates.unify import read_unified
from cobble.experimental.partition.extent_row import ExtentRow
from cobble.experimental.partition.leaf_index import leaf_index

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-matrix",
        description=(
            "Experimental: a field x field positive PMI matrix over the paragraphs "
            "each partition-graph field is read or written in, one column per "
            "unified class."
        ),
    )
    parser.add_argument(
        "--defs",
        type=Path,
        required=True,
        help="defs.jsonl from cobble-dataflow-fixpoint",
    )
    parser.add_argument(
        "--extents", type=Path, required=True, help="extents.jsonl from cobble-extents"
    )
    parser.add_argument(
        "--unified",
        type=Path,
        required=True,
        help="unified.jsonl from cobble-experimental-aggregate-unify",
    )
    parser.add_argument(
        "--min-fields",
        type=int,
        default=3,
        help="fewest distinct fields a paragraph keeps (default 3)",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=5,
        help="fewest paragraphs a field appears in (default 5)",
    )
    parser.add_argument(
        "--min-cooccurrences",
        type=int,
        default=3,
        help="fewest paragraphs a pair shares (default 3)",
    )
    parser.add_argument(
        "--out-matrix", type=Path, required=True, help="output matrix.npz"
    )
    parser.add_argument("--out-meta", type=Path, required=True, help="output meta.json")
    return parser


def _lines(path: Path) -> tuple[DefLine, ...]:
    with path.open(encoding="utf-8") as lines:
        return tuple(
            DefLine.model_validate_json(line) for line in lines if line.strip()
        )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    with arguments.extents.open(encoding="utf-8") as lines:
        index = leaf_index(ExtentRow.model_validate_json(line) for line in lines)
    paragraphs = paragraph_fields(
        _lines(arguments.defs), index, read_unified(arguments.unified)
    )
    found = ppmi_matrix(
        paragraphs,
        MatrixLimits(
            fields_per_paragraph=arguments.min_fields,
            occurrences=arguments.min_occurrences,
            cooccurrences=arguments.min_cooccurrences,
        ),
    )
    save_matrix(found, arguments.out_matrix, arguments.out_meta)
    logger.info("aggregate matrix: -> %s, %s", arguments.out_matrix, arguments.out_meta)
    return 0
