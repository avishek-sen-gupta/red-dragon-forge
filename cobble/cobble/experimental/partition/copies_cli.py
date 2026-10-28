"""cobble-experimental-partition-copies: every place the bytes of one value are copied to or fed from."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator, Mapping, Sequence
from itertools import groupby
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.partition.copies import Copy, CopyWalkError, copies
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.graph_file import read_graph
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

STAGE = "partition copies"


class _RedefinesRow(BaseModel):
    """The names one extents row declares, and the field each redefines."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    program: str
    names: tuple[str, ...]
    redefines: tuple[str, ...]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-copies",
        description=(
            "Experimental: every field, file slot and screen field holding all the bytes "
            "of a value, followed byte by byte through the partition graph."
        ),
    )
    parser.add_argument("--graph", type=Path, required=True, help="graph.jsonl")
    parser.add_argument(
        "--extents", type=Path, required=True, help="extents.jsonl, for REDEFINES"
    )
    parser.add_argument(
        "--width", type=int, required=True, help="how many bytes the value holds"
    )
    parser.add_argument(
        "--start",
        action="append",
        required=True,
        help="a node id holding the value at its offset 0; repeat for several",
    )
    return parser


def _rows(path: Path) -> Iterator[_RedefinesRow]:
    with path.open(encoding="utf-8") as lines:
        yield from (
            _RedefinesRow.model_validate_json(line) for line in lines if line.strip()
        )


def redefines_of(path: Path) -> Mapping[tuple[str, str], str]:
    return {
        (row.program, name): base
        for row in _rows(path)
        for name, base in zip(row.names, row.redefines, strict=True)
        if base
    }


def _program(graph: FieldGraph) -> Mapping[str, str]:
    return {node.id: node.program for node in graph.nodes}


def _label(copy: Copy, program: str) -> str:
    name = copy.node.removeprefix(f"{program}:") if program else copy.node
    return f"{name}+{copy.base}" if copy.base else name


def report(graph: FieldGraph, found: Sequence[Copy]) -> tuple[str, ...]:
    program = _program(graph)
    ordered = sorted(found, key=lambda copy: (program[copy.node], copy.node))
    return (
        *(
            f"{owner or '(files)'}: {', '.join(_label(copy, owner) for copy in group)}"
            for owner, group in groupby(ordered, key=lambda copy: program[copy.node])
        ),
        f"{len(found)} places hold all the bytes",
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    graph = read_graph(arguments.graph)
    logger.info("%s: %d nodes, %d edges", STAGE, len(graph.nodes), len(graph.edges))
    try:
        found = copies(
            graph, redefines_of(arguments.extents), arguments.start, arguments.width
        )
    except CopyWalkError as refused:
        logger.error("%s: %s", STAGE, refused)
        return 2
    sys.stdout.write("\n".join(report(graph, found)) + "\n")
    return 0
