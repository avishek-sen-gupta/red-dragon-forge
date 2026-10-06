"""cobble-srccfg-dfs-walk: what runs, in control-flow order, from one PERFORM
until it returns -- the depth-first counterpart to
cobble-srccfg-reachability-walk's breadth-first rows.

See ``dfs.py`` for exactly what ``--mode tree``/``--mode primary`` mean and
why this is the faithful tool for an execution-*order* question. Output is
plain text (an indented trace plus a distinct-paragraphs summary), not the
CfgRow JSONL `cobble-srccfg-reachability-walk` writes -- the two commands
answer different-shaped questions and are not drop-in replacements for
each other.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import Bundle, CfgDocumentError, load_bundle
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.dfs import primary_walk, tree_walk
from cobble.dataflow.srccfg.reach.reach_error import ReachError

logger = logging.getLogger(__name__)

Walk = Sequence[str]
WalkFn = Callable[[Cfg, str], tuple[Walk, Walk]]
WALKS: Mapping[str, WalkFn] = {"primary": primary_walk, "tree": tree_walk}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-srccfg-dfs-walk",
        description="What runs, in control-flow order, from one PERFORM until it returns.",
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
    parser.add_argument(
        "--mode",
        choices=tuple(WALKS),
        default="primary",
        help="primary: first arm at every branch, alternates noted inline (default). "
        "tree: both arms of every branch, recursed.",
    )
    return parser


def _first_cfg(bundle: Bundle) -> Cfg:
    if not bundle.cfgs:
        raise ReachError("the CFG file holds no program")
    return bundle.cfgs[0]


def _walked(arguments: argparse.Namespace) -> tuple[Walk, Walk]:
    cfg = _first_cfg(load_bundle(arguments.cfg))
    return WALKS[arguments.mode](cfg, arguments.seed)


def _numbered(order: Walk) -> str:
    return "\n".join(f"{i} {paragraph}" for i, paragraph in enumerate(order, 1))


def _rendered(mode: str, lines: Walk, order: Walk) -> str:
    return f"{chr(10).join(lines)}\n\n=== distinct paragraphs, {mode} order ===\n{_numbered(order)}\n"


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    try:
        lines, order = _walked(arguments)
    except (CfgDocumentError, ReachError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    sys.stdout.write(_rendered(arguments.mode, lines, order))
    return 0


if __name__ == "__main__":
    sys.exit(main())
