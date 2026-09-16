"""The call closure of one program: the seed, and what it reaches through calls.

Built for the reader of a single program rather than for a corpus sweep. The seed
comes first and the rest follow in call order, so the output of two runs over the
same cache is diffable.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.build_corpus import cfg_of, cfg_to_dict
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.config import load_srccfg_config
from cobble.dataflow.srccfg.link import call_graph, callees_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bundle:
    seed: str
    cfgs: tuple[Cfg, ...] = ()


def build_closure(asg_dir: Path, seed: str) -> Bundle:
    return Bundle(seed=seed, cfgs=_expand(asg_dir, (seed,), ()))


def _expand(
    asg_dir: Path, pending: tuple[str, ...], built: tuple[Cfg, ...]
) -> tuple[Cfg, ...]:
    """Breadth-first from the seed, one program built once."""
    if not pending:
        return built
    head, *rest = pending
    visit = _visit(asg_dir, head, built, len(rest))
    return _expand(asg_dir, (*rest, *visit.callees), (*built, *visit.cfgs))


@dataclass(frozen=True)
class _Visit:
    """What building one pending program adds: its CFG and the programs it calls,
    both empty when it was already built or is absent from the cache."""

    cfgs: tuple[Cfg, ...] = ()
    callees: tuple[str, ...] = ()


def _visit(asg_dir: Path, program: str, built: tuple[Cfg, ...], pending: int) -> _Visit:
    path = asg_dir / f"{program}.json"
    if program in tuple(cfg.program for cfg in built):
        return _Visit()
    if not path.is_file():
        logger.warning("%s: called but not in the ASG cache; not built", program)
        return _Visit()
    logger.info(
        "srccfg: building %s  (built=%d pending=%d)", program, len(built), pending
    )
    cfg = cfg_of(path)
    logger.info("srccfg: %s done  nodes=%d", program, len(cfg.nodes))
    return _Visit(cfgs=(cfg,), callees=callees_of(call_graph((cfg,)), cfg.program))


def bundle_to_json(bundle: Bundle) -> str:
    """The seed first, then its callees: a list, because the order is the answer's."""
    result = json.dumps([cfg_to_dict(cfg) for cfg in bundle.cfgs])
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the source CFG of one program and the programs it calls."
    )
    parser.add_argument("program", metavar="PROGRAM")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(),
        help="write the closure here instead of stdout",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    """A missing seed is an error, not an empty list.

    An empty list on stdout is a well-formed answer meaning "this program calls
    nothing", and the reader has no way to tell it from "the cache never held the
    program you named".
    """
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    config = load_srccfg_config(arguments.config)
    if not (config.asg_dir / f"{arguments.program}.json").is_file():
        logger.error("%s: no ASG for this program in the cache", arguments.program)
        return 1
    document = bundle_to_json(build_closure(config.asg_dir, arguments.program))
    return _emitted(document, arguments.output)


def _emitted(document: str, output: Path) -> int:
    if output == Path():
        sys.stdout.write(f"{document}\n")
        return 0
    output.write_text(f"{document}\n", encoding="utf-8")
    return 0
