"""What a cached ASG carries per MOVE operand, counted.

Bead 8y0 was filed as a P0 bridge defect and closed as retracted: the evidence
was a cache generated before the bridge emitted structured subscripts. Nothing
downstream can tell a stale cache from a corpus property by reading it, so this
counts the distinction directly and exits non-zero when a cache fails the gate.

Exit status contract:
  0 — all files read successfully, at least one subscripted MOVE operand found
  1 — precondition failed (no subscripted MOVEs found)
  2 — ASG directory not found
  3 — some files were unreadable
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import reduce
from itertools import chain
from pathlib import Path

from cobble.cli_logging import configure_cli_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperandShapes:
    bare: int = 0
    subscripted: int = 0
    ref_modified: int = 0
    total: int = 0
    unreadable: int = 0

    def plus(self, other: OperandShapes) -> OperandShapes:
        return OperandShapes(
            bare=self.bare + other.bare,
            subscripted=self.subscripted + other.subscripted,
            ref_modified=self.ref_modified + other.ref_modified,
            total=self.total + other.total,
            unreadable=self.unreadable + other.unreadable,
        )


def operand_shapes(asg: Mapping) -> OperandShapes:
    return _summed(_shape(operand) for operand in _move_operands(asg))


def _is_move_statement(node: Mapping) -> bool:
    return node.get("type") == "MOVE"


def _walk_mapping(node: Mapping) -> Iterator[Mapping]:
    if _is_move_statement(node):
        yield from node.get("operands") or ()
    yield from chain.from_iterable(_move_operands(v) for v in node.values())


def _walk_sequence(seq: Sequence) -> Iterator[Mapping]:
    yield from chain.from_iterable(_move_operands(item) for item in seq)


def _move_operands(node: Mapping | Sequence) -> Iterator[Mapping]:
    """Yield all MOVE operands from anywhere in the ASG.

    Statements nest through multiple dict keys and compose to arbitrary depth
    (29+ levels observed). Do not enumerate nesting keys — that is how the
    one-level walk missed 2/3 of the MOVEs, and the next statement form the
    bridge learns would silently reopen the hole. Walk the whole document.
    """
    if isinstance(node, Mapping):
        yield from _walk_mapping(node)
    elif isinstance(node, Sequence) and not isinstance(node, str):
        yield from _walk_sequence(node)


def _shape(operand: Mapping) -> OperandShapes:
    subscripted = bool(operand.get("subscripts"))
    ref_modified = bool(operand.get("ref_mod_start"))
    return OperandShapes(
        bare=int(not subscripted and not ref_modified),
        subscripted=int(subscripted),
        ref_modified=int(ref_modified),
        total=1,
    )


def _summed(shapes: Iterator[OperandShapes]) -> OperandShapes:
    return reduce(OperandShapes.plus, shapes, OperandShapes())


def _operand_shapes_guarded(path: Path) -> OperandShapes:
    """Guard each file so one corrupted member does not take the whole diagnostic down."""
    try:
        return operand_shapes(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, AttributeError, RecursionError):
        return OperandShapes(unreadable=1)


def cache_shapes(asg_dir: Path) -> OperandShapes:
    return _summed(
        _operand_shapes_guarded(path) for path in sorted(asg_dir.glob("*.json"))
    )


def _emit_results(shapes: OperandShapes) -> None:
    logger.info(
        "MOVE operands: %d "
        "(bare: %d, subscripted: %d, ref-modified: %d, unreadable: %d)",
        shapes.total,
        shapes.bare,
        shapes.subscripted,
        shapes.ref_modified,
        shapes.unreadable,
    )
    json.dump(asdict(shapes), sys.stdout)
    sys.stdout.write("\n")


def _exit_code(shapes: OperandShapes) -> int:
    if shapes.unreadable:
        return 3
    return 0 if shapes.subscripted else 1


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(
        description="Count MOVE operand shapes across a cached ASG directory."
    )
    parser.add_argument("asg_dir", type=Path)
    arguments = parser.parse_args(tuple(argv) if argv else None)
    if not arguments.asg_dir.is_dir():
        sys.stderr.write(f"No ASG cache at {arguments.asg_dir}\n")
        return 2
    shapes = cache_shapes(arguments.asg_dir)
    _emit_results(shapes)
    return _exit_code(shapes)
