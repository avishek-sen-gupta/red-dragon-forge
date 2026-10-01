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
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.emit import _declared_extents
from cobble.dataflow.fields.program_layout import program_layout
from cobble.dataflow.fields.side_tables import JsonlWriter, extent_row, jsonl_writer
from cobble.dataflow.layout import UnsizeableFieldError
from cobble.path_utils import ensure_parent
from cobol_asg.asg_types import CobolASG

logger = logging.getLogger(__name__)


def _asg_at(path: Path) -> CobolASG:
    with cached_asg_dialect_parsers_registered():
        return CobolASG.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _members(asg_dir: Path) -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in asg_dir.glob("*.json")))


def _emit_one(asg_dir: Path, member: str, writer: JsonlWriter) -> str:
    """One member's rows, or the reason it has none.

    Every failure is a reason rather than an abort, which matters more now that the
    fixpoint stage reads its records here: one member's broken cache file would
    otherwise cost every other member in the corpus its layout, and that stage its
    whole input.
    """
    try:
        layout = program_layout(_asg_at(asg_dir / f"{member}.json"))
    except UnsizeableFieldError as unsizeable:
        return f"unsizeable: {unsizeable}"
    except Exception as failure:  # noqa: BLE001 - one member must not end the run
        return f"unreadable: {failure!r}"
    writer.add_rows(extent_row(ext) for ext in _declared_extents(layout, member))
    return ""


def _emit_tracked(
    asg_dir: Path, n: int, total: int, member: str, writer: JsonlWriter
) -> str:
    reason = _emit_one(asg_dir, member, writer)
    if n % 50 == 0 or n == total:
        logger.info("extents: %d/%d", n, total)
    return reason


def emit(asg_dir: Path, out: Path, members: Sequence[str]) -> int:
    chosen = members if members else _members(asg_dir)
    total = len(chosen)
    logger.info("extents: %d members from %s", total, asg_dir)
    ensure_parent(out)
    with jsonl_writer(out) as writer:
        skipped = tuple(
            member
            for n, member in enumerate(chosen, 1)
            for reason in (_emit_tracked(asg_dir, n, total, member, writer),)
            if reason and not logger.warning("extents: skipping %s: %s", member, reason)
        )
    logger.info("extents: wrote %s (%d skipped)", out, len(skipped))
    return 3 if skipped else 0


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
    return emit(arguments.asg_dir, arguments.out, arguments.members)


def main() -> int:
    sys.exit(cli())
