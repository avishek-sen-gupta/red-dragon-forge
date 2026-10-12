"""IDCAMS command executor: runs the parsed commands in order and returns the final MAXCC."""

from __future__ import annotations

import operator
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import chain, count, takewhile
from typing import TypeAlias

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver
from jackal.allocation import (
    ConcatenatedAllocation,
    DatasetAllocation,
    DdEnvironment,
    DummyAllocation,
    MemberAllocation,
)
from jackal.catalog import DatasetCatalog
from jackal.dataset import Dataset
from jackal.idcams.commands import (
    Cancel,
    Cc,
    CcOp,
    Command,
    Condition,
    DefineCluster,
    DefineGdg,
    Delete,
    If,
    NotExecuted,
    Repro,
    SetCc,
    Verify,
    VerifyDataset,
    VerifyFile,
)
from jackal.labels import DatasetLabel, KsdsLabel, LabelPending
from jackal.model import DdName
from jackal.system_catalog import NotCataloged

_TESTS: Mapping[CcOp, Callable[[int, int], bool]] = {
    CcOp.LE: operator.le,
    CcOp.LT: operator.lt,
    CcOp.GE: operator.ge,
    CcOp.GT: operator.gt,
    CcOp.EQ: operator.eq,
    CcOp.NE: operator.ne,
}


_OPEN_FAILED = 12
_LOGICAL_ERROR = 12
_NOT_FOUND = 8
_STREAM_ENDED = 16


@dataclass(frozen=True)
class _Codes:
    lastcc: int
    maxcc: int
    ended: bool


def _ran(codes: _Codes, rc: int) -> _Codes:
    return _Codes(rc, max(codes.maxcc, rc), rc >= _STREAM_ENDED)


def _tested(codes: _Codes, condition: Condition) -> bool:
    counter = codes.lastcc if condition.field is Cc.LASTCC else codes.maxcc
    return _TESTS[condition.op](counter, condition.value)


def _set(codes: _Codes, cmd: SetCc) -> _Codes:
    value = min(cmd.value, _STREAM_ENDED)
    ended = value == _STREAM_ENDED
    if cmd.field is Cc.MAXCC:
        return _Codes(codes.lastcc, value, ended)
    return _Codes(value, max(codes.maxcc, value), ended)


def _verified(labels: tuple[DatasetLabel, ...]) -> int:
    return 0 if any(isinstance(label, KsdsLabel) for label in labels) else _OPEN_FAILED


def _cataloged(catalog: DatasetCatalog, name: str) -> tuple[DatasetLabel, ...]:
    match catalog.resolve(name):
        case Dataset() as found:
            return (found.label,)
        case NotCataloged():
            return ()


def _handle_verify(cmd: Verify, dds: DdEnvironment, catalog: DatasetCatalog) -> int:
    match cmd.target:
        case VerifyFile(ddname=ddname):
            return _verified(tuple(d.label for d in dds.datasets(DdName(ddname))))
        case VerifyDataset(name=name):
            return _verified(_cataloged(catalog, name))


def _deleted_rc(entry: str, catalog: DatasetCatalog) -> int:
    return 0 if catalog.delete_dsn(entry) else _NOT_FOUND


def _handle_delete(cmd: Delete, catalog: DatasetCatalog) -> int:
    return max(_deleted_rc(entry, catalog) for entry in cmd.entries)


def _handle_define_cluster(cmd: DefineCluster, catalog: DatasetCatalog) -> int:
    try:
        catalog.define(
            cmd.name, KsdsLabel(cmd.record_size, cmd.key_offset, cmd.key_length)
        )
    except ValueError:
        return 12
    return 0


def _handle_define_gdg(cmd: DefineGdg, catalog: DatasetCatalog) -> int:
    if not cmd.within_limit():
        return _LOGICAL_ERROR
    try:
        catalog.define_gdg(cmd.base())
    except ValueError:
        return _LOGICAL_ERROR
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


@dataclass(frozen=True)
class _Dummy:
    """A DUMMY DD: an immediate end of file to read, a discard to write."""


def _side(dds: DdEnvironment, ddname: str) -> Dataset | _Dummy:
    match dds.get(DdName(ddname)):
        case DummyAllocation():
            return _Dummy()
        case _:
            return dds.dataset(DdName(ddname))


def _member(allocation: MemberAllocation) -> Dataset | _Dummy:
    match allocation:
        case DummyAllocation():
            return _Dummy()
        case DatasetAllocation(dataset=dataset):
            return dataset
        case _:
            raise TypeError(f"REPRO cannot read {type(allocation).__name__}")


def _sources(dds: DdEnvironment, ddname: str) -> tuple[Dataset | _Dummy, ...]:
    match dds.get(DdName(ddname)):
        case ConcatenatedAllocation(members=members):
            return tuple(map(_member, members))
        case allocation:
            return (_member(allocation),)


def _unreadable(source: Dataset | _Dummy, sink: Dataset | _Dummy) -> bool:
    match (source, sink):
        case (Dataset(label=LabelPending()), _):
            return True
        case (Dataset(), Dataset()):
            return source.dsn == sink.dsn
        case _:
            return False


def _handle_repro(cmd: Repro, dds: DdEnvironment) -> int:
    sources = _sources(dds, cmd.infile_dd)
    sink = _side(dds, cmd.outfile_dd)
    if any(_unreadable(source, sink) for source in sources):
        return _OPEN_FAILED
    return _written(chain.from_iterable(map(_member_records, sources)), sink)


def _member_records(source: Dataset | _Dummy) -> Iterator[bytes]:
    match source:
        case _Dummy():
            return iter(())
        case Dataset():
            return _read(source)


def _read(source: Dataset) -> Iterator[bytes]:
    driver = source.opened(OpenMode.INPUT)
    yield from _records(driver)
    driver.close()


def _written(records: Iterable[bytes], sink: Dataset | _Dummy) -> int:
    match sink:
        case _Dummy():
            return 0
        case Dataset():
            return _filled(records, sink.opened(OpenMode.OUTPUT))


def _filled(records: Iterable[bytes], driver: FileOrganizationDriver) -> int:
    for record in records:
        driver.write(record)
    driver.close()
    return 0


_Functional: TypeAlias = (
    Delete | DefineCluster | DefineGdg | Repro | Verify | NotExecuted
)


def _functional_rc(
    cmd: _Functional, dds: DdEnvironment, catalog: DatasetCatalog
) -> int:
    match cmd:
        case NotExecuted():
            return _LOGICAL_ERROR
        case _:
            return _executed_rc(cmd, dds, catalog)


def _executed_rc(
    cmd: Delete | DefineCluster | DefineGdg | Repro | Verify,
    dds: DdEnvironment,
    catalog: DatasetCatalog,
) -> int:
    match cmd:
        case Repro():
            return _handle_repro(cmd, dds)
        case Verify():
            return _handle_verify(cmd, dds, catalog)
        case _:
            return _catalog_rc(cmd, catalog)


def _catalog_rc(
    cmd: Delete | DefineCluster | DefineGdg, catalog: DatasetCatalog
) -> int:
    match cmd:
        case Delete():
            return _handle_delete(cmd, catalog)
        case _:
            return _define_rc(cmd, catalog)


def _define_rc(cmd: DefineCluster | DefineGdg, catalog: DatasetCatalog) -> int:
    match cmd:
        case DefineCluster():
            return _handle_define_cluster(cmd, catalog)
        case DefineGdg():
            return _handle_define_gdg(cmd, catalog)


@dataclass(frozen=True)
class _Stream:
    """One IDCAMS invocation: commands run in order until the stream ends."""

    dds: DdEnvironment
    catalog: DatasetCatalog

    def run(self, commands: Sequence[Command], codes: _Codes) -> _Codes:
        return reduce(self._step, commands, codes)

    def _step(self, codes: _Codes, cmd: Command) -> _Codes:
        if codes.ended:
            return codes
        return self._command(codes, cmd)

    def _command(self, codes: _Codes, cmd: Command) -> _Codes:
        match cmd:
            case If():
                return self._branch(codes, cmd)
            case _:
                return self._simple(codes, cmd)

    def _branch(self, codes: _Codes, cmd: If) -> _Codes:
        taken = cmd.then if _tested(codes, cmd.condition) else cmd.otherwise
        return self.run(taken, codes)

    def _simple(self, codes: _Codes, cmd: _Functional | SetCc | Cancel) -> _Codes:
        match cmd:
            case SetCc():
                return _set(codes, cmd)
            case _:
                return self._ended_or_ran(codes, cmd)

    def _ended_or_ran(self, codes: _Codes, cmd: _Functional | Cancel) -> _Codes:
        match cmd:
            case Cancel():
                return _Codes(codes.lastcc, codes.maxcc, True)
            case _:
                return _ran(codes, _functional_rc(cmd, self.dds, self.catalog))


def run_idcams(
    commands: Sequence[Command],
    dds: DdEnvironment,
    catalog: DatasetCatalog,
) -> int:
    return _Stream(dds, catalog).run(commands, _Codes(0, 0, False)).maxcc
