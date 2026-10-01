"""The call closure of one program: the seed, and what it reaches through calls.

Built for the reader of a single program rather than for a corpus sweep. The seed
comes first and the rest follow in call order, so the output of two runs over the
same cache is diffable.

What joins the CFGs travels with them: the bundle carries every call site and the
entry node it lands on, so a reader crosses between programs by following a call
rather than by rebuilding the call graph. bundle.py is the file that holds both.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate, repeat
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.build_corpus import cfg_of, source_file_of
from cobble.dataflow.srccfg.bundle import Bundle, bundle_to_json
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.config import load_srccfg_build_config
from cobble.dataflow.srccfg.dynamic_targets import (
    NO_DYNAMIC_TARGETS,
    DynamicTargets,
    dynamic_targets_of,
)
from cobble.dataflow.srccfg.link import (
    bundle_calls,
    call_graph,
    callees_of,
    dynamic_callees,
)
from cobble.path_utils import ensure_parent

logger = logging.getLogger(__name__)


def build_closure(
    asg_dir: Path,
    seed: str,
    source_dir: Path,
    targets: DynamicTargets = NO_DYNAMIC_TARGETS,
) -> Bundle:
    """``targets`` turns each dynamic call site it answers into calls to its
    candidates, and builds them like any callee."""
    cfgs = _expand(asg_dir, source_dir, targets, (seed,), ())
    return Bundle(seed=seed, cfgs=cfgs, calls=bundle_calls(cfgs, targets))


def _expand(
    asg_dir: Path,
    source_dir: Path,
    targets: DynamicTargets,
    pending: tuple[str, ...],
    built: tuple[Cfg, ...],
) -> tuple[Cfg, ...]:
    """Breadth-first from the seed, one program built once.

    Stepped rather than recursive: a closure is as long as the call chains it
    follows, and a recursive walk dies at the interpreter's thousand frames.
    """
    walks = accumulate(
        repeat(None),
        lambda walk, _: _step(asg_dir, source_dir, targets, walk),
        initial=_Walk(pending=pending, built=built),
    )
    return next(walk for walk in walks if not walk.pending).built


@dataclass(frozen=True)
class _Walk:
    """The programs still to visit, in order, and the CFGs built so far."""

    pending: tuple[str, ...]
    built: tuple[Cfg, ...]


def _step(
    asg_dir: Path, source_dir: Path, targets: DynamicTargets, walk: _Walk
) -> _Walk:
    head, *rest = walk.pending
    visit = _visit(asg_dir, source_dir, targets, head, walk.built, len(rest))
    return _Walk(pending=(*rest, *visit.callees), built=(*walk.built, *visit.cfgs))


@dataclass(frozen=True)
class _Visit:
    """What building one pending program adds: its CFG and the programs it calls,
    both empty when it was already built or is absent from the cache."""

    cfgs: tuple[Cfg, ...] = ()
    callees: tuple[str, ...] = ()


def _visit(
    asg_dir: Path,
    source_dir: Path,
    targets: DynamicTargets,
    program: str,
    built: tuple[Cfg, ...],
    pending: int,
) -> _Visit:
    path = asg_dir / f"{program}.json"
    if program in tuple(cfg.program for cfg in built):
        return _Visit()
    if not path.is_file():
        logger.warning("%s: called but not in the ASG cache; not built", program)
        return _Visit()
    logger.info(
        "srccfg: building %s  (built=%d pending=%d)", program, len(built), pending
    )
    cfg = cfg_of(path, source_file=source_file_of(source_dir, program))
    logger.info("srccfg: %s done  nodes=%d", program, len(cfg.nodes))
    callees = {
        *callees_of(call_graph((cfg,)), cfg.program),
        *dynamic_callees(cfg, targets),
    }
    return _Visit(cfgs=(cfg,), callees=tuple(sorted(callees)))


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
    parser.add_argument(
        "--dynamic-call-targets",
        type=_dynamic_call_targets,
        default=NO_DYNAMIC_TARGETS,
        help="The targets.jsonl cobble-dataflow-fixpoint wrote: each dynamic "
        "CALL/XCTL/LINK site's candidates are built and joined like any callee. "
        "Without it, dynamic sites pull in nothing",
    )
    return parser


def _dynamic_call_targets(text: str) -> DynamicTargets:
    path = Path(text)
    if not path.is_file():
        raise argparse.ArgumentTypeError(
            f"{path} not found — cobble-dataflow-fixpoint writes targets.jsonl "
            "into its --out-dir"
        )
    return dynamic_targets_of(path)


def main(argv: Sequence[str] = ()) -> int:
    """A missing seed is an error, not an empty bundle.

    A bundle of no programs on stdout is a well-formed answer meaning "this program
    calls nothing", and the reader has no way to tell it from "the cache never held
    the program you named".
    """
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    config = load_srccfg_build_config(arguments.config)
    if not (config.asg_dir / f"{arguments.program}.json").is_file():
        logger.error("%s: no ASG for this program in the cache", arguments.program)
        return 1
    document = bundle_to_json(
        build_closure(
            config.asg_dir,
            arguments.program,
            config.source_dir,
            arguments.dynamic_call_targets,
        )
    )
    return _emitted(document, arguments.output)


def _emitted(document: str, output: Path) -> int:
    if output == Path():
        sys.stdout.write(f"{document}\n")
        return 0
    ensure_parent(output).write_text(f"{document}\n", encoding="utf-8")
    return 0
