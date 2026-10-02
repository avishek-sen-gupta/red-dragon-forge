"""The one shape a CFG file has, and the only code that reads or writes it.

One JSON row per line: a ``program`` row opening each CFG, then its ``node`` rows,
then its ``edge`` rows, and the ``call`` rows joining the programs after all of
them. The first program is the bundle's seed. A corpus member is a file with one
program and no calls; a closure is the same file with more.

Rows rather than one document so a file can be written and read as it streams. A
line that is not a row -- the one-document shape this replaced, or a row cut off
mid-write -- is refused with its line number, and ``cobble-srccfg-build``
regenerates the file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import TypeVar

from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.link import BundleCall
from cobble.dataflow.srccfg.rows.call_row import CfgCallRow
from cobble.dataflow.srccfg.rows.cfg_row import (
    CFG_ROWS,
    CfgRow,
    call_row,
    edge_row,
    node_row,
    program_row,
)
from cobble.dataflow.srccfg.rows.edge_row import CfgEdgeRow
from cobble.dataflow.srccfg.rows.node_row import CfgNodeRow
from cobble.dataflow.srccfg.rows.program_row import CfgProgramRow
from pydantic import ValidationError

REBUILD_HINT = "rebuild it with cobble-srccfg-build"

RowT = TypeVar("RowT", CfgNodeRow, CfgEdgeRow)


class CfgDocumentError(ValueError):
    """A CFG file that is not in the one shape, named so a caller can say which."""


@dataclass(frozen=True)
class Bundle:
    seed: str
    cfgs: tuple[Cfg, ...] = ()
    calls: tuple[BundleCall, ...] = ()


def rows_of(bundle: Bundle) -> tuple[CfgRow, ...]:
    return (
        *(row for cfg in bundle.cfgs for row in _cfg_rows(cfg)),
        *(call_row(call) for call in bundle.calls),
    )


def _cfg_rows(cfg: Cfg) -> tuple[CfgRow, ...]:
    return (
        program_row(cfg.program),
        *(node_row(cfg.program, node) for node in cfg.nodes),
        *(edge_row(cfg.program, edge) for edge in cfg.edges),
    )


def bundle_jsonl(bundle: Bundle) -> str:
    return "".join(f"{row.model_dump_json()}\n" for row in rows_of(bundle))


def load_bundle(path: Path) -> Bundle:
    return bundle_of_rows(
        tuple(
            _row(line, f"{path.name}:{at}")
            for at, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip()
        ),
        path.name,
    )


def _row(line: str, where: str) -> CfgRow:
    try:
        return CFG_ROWS.validate_json(line)
    except ValidationError as error:
        raise CfgDocumentError(f"{where}: not a CFG row -- {REBUILD_HINT}") from error


def bundle_of_rows(rows: Sequence[CfgRow], source: str = "<rows>") -> Bundle:
    programs = tuple(row.program for row in rows if isinstance(row, CfgProgramRow))
    order = {program: at for at, program in enumerate(programs)}
    nodes = _by_program(
        tuple(row for row in rows if isinstance(row, CfgNodeRow)), order, source
    )
    edges = _by_program(
        tuple(row for row in rows if isinstance(row, CfgEdgeRow)), order, source
    )
    return Bundle(
        seed=programs[0] if programs else "",
        cfgs=tuple(
            Cfg(
                program=program,
                nodes=tuple(row.to_node() for row in nodes.get(program, ())),
                edges=tuple(row.to_edge() for row in edges.get(program, ())),
            )
            for program in programs
        ),
        calls=tuple(row.to_call() for row in rows if isinstance(row, CfgCallRow)),
    )


def _by_program(
    rows: tuple[RowT, ...], order: Mapping[str, int], source: str
) -> Mapping[str, tuple[RowT, ...]]:
    """Each program's rows in file order. A stable sort by the program's position
    keeps a program's own rows in the order they were written."""
    strays = sorted({row.program for row in rows} - order.keys())
    if strays:
        raise CfgDocumentError(
            f"{source}: rows for {', '.join(strays)} with no program row -- {REBUILD_HINT}"
        )
    ordered = sorted(rows, key=lambda row: order[row.program])
    return {
        program: tuple(group)
        for program, group in groupby(ordered, key=attrgetter("program"))
    }
