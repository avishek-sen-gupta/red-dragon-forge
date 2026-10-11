"""IDCAMS command executor: runs the parsed commands in order and returns the final MAXCC."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import count, takewhile

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver
from jackal.allocation import DdEnvironment
from jackal.catalog import DatasetCatalog
from jackal.dataset import Dataset
from jackal.idcams.commands import (
    Command,
    DefineCluster,
    Delete,
    IfMaxcc,
    Repro,
    SetMaxcc,
)
from jackal.labels import KsdsLabel, LabelPending
from jackal.model import DdName

_OPS: Mapping[str, Callable[[int, int], bool]] = {
    "LE": lambda maxcc, value: maxcc <= value,
    "LT": lambda maxcc, value: maxcc < value,
    "GE": lambda maxcc, value: maxcc >= value,
    "GT": lambda maxcc, value: maxcc > value,
    "EQ": lambda maxcc, value: maxcc == value,
    "NE": lambda maxcc, value: maxcc != value,
}


_OPEN_FAILED = 12


@dataclass(frozen=True)
class _Codes:
    lastcc: int
    maxcc: int


def _handle_delete(cmd: Delete, catalog: DatasetCatalog) -> int:
    return 0 if catalog.delete_dsn(cmd.dsn) else 8


def _handle_define_cluster(cmd: DefineCluster, catalog: DatasetCatalog) -> int:
    try:
        catalog.define(
            cmd.name, KsdsLabel(cmd.record_size, cmd.key_offset, cmd.key_length)
        )
    except ValueError:
        return 12
    return 0


def _data(result: AccessResult) -> bytes:
    match result.data:
        case bytes() as data:
            return data
        case _:
            raise ValueError("driver returned non-EOF with no data")


def _records(driver: FileOrganizationDriver) -> Iterator[bytes]:
    reads = (driver.read_seq() for _ in count())
    return map(
        _data,
        takewhile(lambda r: r.condition is not AccessCondition.END_OF_FILE, reads),
    )


def _handle_repro(cmd: Repro, dds: DdEnvironment) -> int:
    in_ds = dds.dataset(DdName(cmd.infile_dd))
    match in_ds.label:
        case LabelPending():
            return _OPEN_FAILED
        case _:
            return _copied(in_ds, dds.dataset(DdName(cmd.outfile_dd)))


def _copied(in_ds: Dataset, out_ds: Dataset) -> int:
    in_drv = in_ds.opened(OpenMode.INPUT, in_ds.record_size())
    out_drv = out_ds.opened(OpenMode.OUTPUT, out_ds.record_size())
    for record in _records(in_drv):
        out_drv.write(record)
    in_drv.close()
    out_drv.close()
    return 0


def _functional_rc(
    cmd: Delete | DefineCluster | Repro, dds: DdEnvironment, catalog: DatasetCatalog
) -> int:
    match cmd:
        case Repro():
            return _handle_repro(cmd, dds)
        case _:
            return _catalog_rc(cmd, catalog)


def _catalog_rc(cmd: Delete | DefineCluster, catalog: DatasetCatalog) -> int:
    match cmd:
        case Delete():
            return _handle_delete(cmd, catalog)
        case _:
            return _handle_define_cluster(cmd, catalog)


def _if_maxcc(cmd: IfMaxcc, codes: _Codes) -> _Codes:
    tested = codes.lastcc if cmd.test_field == "LASTCC" else codes.maxcc
    holds = _OPS[cmd.op](tested, cmd.value)
    return _Codes(codes.lastcc, cmd.set_value if holds else tested)


def _control(cmd: IfMaxcc | SetMaxcc, codes: _Codes) -> _Codes:
    match cmd:
        case IfMaxcc():
            return _if_maxcc(cmd, codes)
        case _:
            return _Codes(codes.lastcc, cmd.value)


def _step(
    dds: DdEnvironment, catalog: DatasetCatalog, codes: _Codes, cmd: Command
) -> _Codes:
    match cmd:
        case IfMaxcc() | SetMaxcc():
            return _control(cmd, codes)
        case _:
            lastcc = _functional_rc(cmd, dds, catalog)
            return _Codes(lastcc, max(codes.maxcc, lastcc))


def run_idcams(
    commands: Sequence[Command],
    dds: DdEnvironment,
    catalog: DatasetCatalog,
) -> int:
    return reduce(
        lambda codes, cmd: _step(dds, catalog, codes, cmd), commands, _Codes(0, 0)
    ).maxcc
