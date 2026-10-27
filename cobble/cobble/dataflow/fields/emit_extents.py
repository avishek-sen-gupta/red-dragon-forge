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
from cobble.dataflow.fields.extents_options import ExtentsOptions
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.side_tables import (
    JsonlWriter,
    _Row,
    extent_row,
    jsonl_writer,
)
from cobble.dataflow.fields.undeclared import with_undeclared
from cobble.dataflow.layout import UnsizeableFieldError
from cobble.parsing.asg_cache import first_program_at
from cobble.path_utils import ensure_parent
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)


def _asg_at(path: Path) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return first_program_at(path)


def _members(asg_dir: Path) -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in asg_dir.glob("*.json")))


_Names = tuple[tuple[str, ...], ...]
_LaidOut = tuple[tuple[_Row, ...], str, float, _Names]

LISTED = 10


def _prepared(asg: CobolASG, undeclared: bool) -> tuple[CobolASG, _Names]:
    return with_undeclared(asg) if undeclared else (asg, ())


def _laid_out(asg_dir: Path, member: str, undeclared: bool) -> _LaidOut:
    """One member's rows, or the reason it has none, how long it took, and the names it
    declared because the program used them without declaring them.

    Runs in a worker process, so it writes and logs nothing: the parent owns the
    one writer and the report. Every failure is a reason rather than an abort --
    one member's broken cache file must not cost every other member its layout,
    and the fixpoint stage its whole input.
    """
    started = time.monotonic()
    try:
        asg, names = _prepared(_asg_at(asg_dir / f"{member}.json"), undeclared)
        layout = program_layout(asg)
    except UnsizeableFieldError as unsizeable:
        return (), f"unsizeable: {unsizeable}", time.monotonic() - started, ()
    except Exception as failure:  # noqa: BLE001 - one member must not end the run
        return (), f"unreadable: {failure!r}", time.monotonic() - started, ()
    rows = tuple(extent_row(ext) for ext in _declared_extents(layout, member))
    return rows, "", time.monotonic() - started, names


def _written(
    numbered: tuple[int, tuple[str, _LaidOut]],
    total: int,
    writer: JsonlWriter,
) -> str:
    """Write one member's rows and report it; the reason it was skipped, or ""."""
    n, (member, (rows, reason, seconds, names)) = numbered
    if reason:
        logger.warning("extents: [%d/%d] %s skipped: %s", n, total, member, reason)
        return reason
    writer.add_rows(rows)
    logger.info(
        "extents: [%d/%d] %s %d rows, %.1fs", n, total, member, len(rows), seconds
    )
    if names:
        logger.info(
            "extents: %s declared %d names it uses but never declares: %s%s",
            member,
            len(names),
            ", ".join(" OF ".join(reversed(path)) for path in names[:LISTED]),
            ", ..." if len(names) > LISTED else "",
        )
    return ""


def emit(
    asg_dir: Path, out: Path, members: Sequence[str], options: ExtentsOptions
) -> int:
    """Lay members out across worker processes, writing them in member order.

    Workers finish out of order; ``map`` hands results back in submission order,
    so the table is the one a serial run writes, byte for byte.
    """
    chosen = members if members else _members(asg_dir)
    total = len(chosen)
    logger.info(
        "extents: %d members from %s, %d workers", total, asg_dir, options.max_workers
    )
    ensure_parent(out)
    with (
        ProcessPoolExecutor(max_workers=options.max_workers) as pool,
        jsonl_writer(out) as writer,
    ):
        results = pool.map(
            _laid_out, repeat(asg_dir), chosen, repeat(options.undeclared)
        )
        skipped = tuple(
            reason
            for numbered in enumerate(zip(chosen, results, strict=True), 1)
            for reason in (_written(numbered, total, writer),)
            if reason
        )
    logger.info("extents: wrote %s (%d skipped)", out, len(skipped))
    return 3 if skipped else 0


def worker_count(given: str) -> int:
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
        type=worker_count,
        default=4,
        help="worker processes laying members out in parallel (default 4)",
    )
    parser.add_argument(
        "--synthesize-undeclared",
        action="store_true",
        help="declare every field name a program uses but never declares, as when its"
        " copybook is missing, as PIC X(10) in WORKING-STORAGE (under its qualifiers;"
        " OCCURS 10 where subscripted), so the fixpoint tracks it",
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
        arguments.asg_dir,
        arguments.out,
        arguments.members,
        ExtentsOptions(
            max_workers=arguments.max_workers,
            undeclared=arguments.synthesize_undeclared,
        ),
    )


def main() -> int:
    sys.exit(cli())
