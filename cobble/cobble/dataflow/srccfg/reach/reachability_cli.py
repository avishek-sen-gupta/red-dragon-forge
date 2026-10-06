"""cobble-srccfg-reachability-walk: what can run from one PERFORM until it
returns, as src-cfg rows.

Reads a CFG file cobble-srccfg-build wrote, walks the first program in it from the
PERFORM node named by --from, and writes the reached subgraph and what it found to
stdout as JSONL, as the walk goes. cobble-srccfg-dot and -webgl render the output.

This is reachability, level by level from the seed -- not execution order
(a node closer to the seed in graph distance can print before one that
actually runs first). For "what executes, in order", see
cobble-srccfg-dfs-walk (``reach/dfs_cli.py``), which drives the exact same
stepper depth-first instead.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import Bundle, CfgDocumentError, load_bundle
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.reach_error import ReachError
from cobble.dataflow.srccfg.reach.walk import reach_rows
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-srccfg-reachability-walk",
        description="Everything that can run from one PERFORM until it returns.",
    )
    parser.add_argument(
        "--cfg",
        required=True,
        type=Path,
        help="a CFG file cobble-srccfg-build wrote; the walk runs in its first program",
    )
    parser.add_argument(
        "--from",
        dest="seed",
        required=True,
        help="the id of a PERFORM node in that program, e.g. MAIN-PARA/0",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    try:
        rows = reach_rows(_walked_program(arguments.cfg), arguments.seed)
    except (CfgDocumentError, ReachError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    return _written(rows)


def _written(rows: Iterator[CfgRow]) -> int:
    """Rows to stdout as the walk makes them. A reader that stops early -- ``| head``
    -- closes the pipe; that ends the command, quietly, rather than as a traceback,
    and stdout is pointed at /dev/null so the interpreter's own final flush cannot
    raise it again."""
    try:
        sys.stdout.writelines(f"{row.model_dump_json()}\n" for row in rows)
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


def _walked_program(path: Path) -> Cfg:
    return _first(load_bundle(path))


def _first(bundle: Bundle) -> Cfg:
    if not bundle.cfgs:
        raise ReachError("the CFG file holds no program")
    return bundle.cfgs[0]
