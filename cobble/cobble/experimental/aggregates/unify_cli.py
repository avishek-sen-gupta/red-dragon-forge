"""cobble-experimental-aggregate-unify: unify differently-named fields through byte-offset matching."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.aggregates.unify import unify_fields, write_unified

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-aggregate-unify",
        description=(
            "Experimental: unify differently-named fields that occupy the same bytes "
            "across inter-program call boundaries, using the alias and extent tables."
        ),
    )
    parser.add_argument(
        "--aliases", type=Path, required=True,
        help="aliases.jsonl from cobble-dataflow-fixpoint",
    )
    parser.add_argument(
        "--extents", type=Path, required=True,
        help="extents JSONL from cobble-extents (the full field layout dictionary)",
    )
    parser.add_argument(
        "--out", type=Path, required=True,
        help="output unified.jsonl: one line per equivalence class",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    uf = unify_fields(arguments.aliases, arguments.extents)
    n = write_unified(arguments.out, uf)
    logger.info("aggregate unify: %d classes with 2+ members -> %s", n, arguments.out)
    return 0
