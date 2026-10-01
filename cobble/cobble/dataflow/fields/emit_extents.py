"""Declared extents for every member in an ASG cache, with no analysis.

A field's byte ranges follow from its declaration alone — level, usage, OCCURS,
REDEFINES — and need no fixpoint, no flow, no JVM. This is the layout table both
the fixpoint artefact and the path-sampled trace query against, and the one the
fixpoint stage reads its records back out of rather than laying them out again.

Rows carry the member they came from, not the PROGRAM-ID it declares: this stage
never looks inside the program, and a member whose id disagrees with its file name
is still the member a caller asked for.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import _declared_extents
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.side_tables import (
    JsonlWriter,
    _Row,
    extent_row,
    jsonl_writer,
)
from cobble.dataflow.layout import UnsizeableFieldError
from cobble.path_utils import ensure_parent
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)


def _asg_at(path: Path) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _members(asg_dir: Path) -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in asg_dir.glob("*.json")))


def _laid_out(asg_dir: Path, member: str) -> tuple[tuple[_Row, ...], str, float]:
    """One member's rows, or the reason it has none, and how long it took.

    Runs in a worker process, so it writes and logs nothing: the parent owns the
    one writer and the report. Every failure is a reason rather than an abort --
    one member's broken cache file must not cost every other member its layout,
    and the fixpoint stage its whole input.
    """
    started = time.monotonic()
    try:
        layout = program_layout(_asg_at(asg_dir / f"{member}.json"))
    except UnsizeableFieldError as unsizeable:
        return (), f"unsizeable: {unsizeable}", time.monotonic() - started
    except Exception as failure:  # noqa: BLE001 - one member must not end the run
        return (), f"unreadable: {failure!r}", time.monotonic() - started
    rows = tuple(extent_row(ext) for ext in _declared_extents(layout, member))
    return rows, "", time.monotonic() - started


def _written(
    numbered: tuple[int, tuple[str, tuple[tuple[_Row, ...], str, float]]],
    total: int,
    writer: JsonlWriter,
) -> str:
    """Write one member's rows and report it; the reason it was skipped, or ""."""
    n, (member, (rows, reason, seconds)) = numbered
    if reason:
        logger.warning("extents: [%d/%d] %s skipped: %s", n, total, member, reason)
        return reason
    writer.add_rows(rows)
    logger.info(
        "extents: [%d/%d] %s %d rows, %.1fs", n, total, member, len(rows), seconds
    )
    return ""


def emit(asg_dir: Path, out: Path, members: Sequence[str], max_workers: int) -> int:
    """Lay members out across worker processes, writing them in member order.

    Workers finish out of order; ``map`` hands results back in submission order,
    so the table is the one a serial run writes, byte for byte.
    """
    chosen = members if members else _members(asg_dir)
    total = len(chosen)
    logger.info("extents: %d members from %s, %d workers", total, asg_dir, max_workers)
    ensure_parent(out)
    with (
        ProcessPoolExecutor(max_workers=max_workers) as pool,
        jsonl_writer(out) as writer,
    ):
        results = pool.map(_laid_out, repeat(asg_dir), chosen)
        skipped = tuple(
            reason
            for numbered in enumerate(zip(chosen, results, strict=True), 1)
            for reason in (_written(numbered, total, writer),)
            if reason
        )
    logger.info("extents: wrote %s (%d skipped)", out, len(skipped))
    return 3 if skipped else 0


def _workers(given: str) -> int:
    """No worker lays out no member, so a count below one is a usage error."""
    count = int(given)
    if count < 1:
        raise argparse.ArgumentTypeError(f"needs at least one worker, got {count}")
    return count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write declared field extents from an ASG cache, no analysis needed."
    )
    parser.add_argument(
        "--asg-dir", required=True, type=Path, help="the parsed ASG cache directory"
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="where to write extents.jsonl"
    )
    parser.add_argument(
        "--max-workers",
        type=_workers,
        default=4,
        help="worker processes laying members out in parallel (default 4)",
    )
    parser.add_argument(
        "members",
        nargs="*",
        help="members to emit (default: all *.json in asg-dir)",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    if not arguments.asg_dir.is_dir():
        logger.error("extents: no ASG cache at %s", arguments.asg_dir)
        return 2
    return emit(
        arguments.asg_dir, arguments.out, arguments.members, arguments.max_workers
    )


def main() -> int:
    sys.exit(cli())
