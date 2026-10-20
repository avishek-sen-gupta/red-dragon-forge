"""CICS file control over the system catalog's datasets: a cluster or a path per CICS file."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from catnip.catalog_stores import Table
from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView
from cics.vsam.eibresp import (
    RESP_DISABLED,
    RESP_INVREQ,
    RESP_NORMAL,
    RESP_NOTFND,
    to_eibresp,
)
from cics.vsam.key_match import KeyMatch
from cics.vsam.no_record import NoRecord
from cics.vsam.read_outcome import ReadOutcome
from cics.vsam.record_read import RecordRead
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver

logger = logging.getLogger(__name__)

_CursorKey = tuple[str, str, str]

_RETURNS_RECORD = frozenset({AccessCondition.OK, AccessCondition.DUPLICATES_FOLLOW})


@dataclass(frozen=True)
class _Shape:
    """A CICS file's record length and key position, as its catalog label declares them."""

    lrecl: int
    key_offset: int
    key_length: int


@dataclass(frozen=True)
class _NoFile:
    """A CICS file name the region's file table does not define."""


def _shape(dataset: Dataset) -> _Shape:
    match dataset.label:
        case KsdsLabel() as ksds:
            return _Shape(ksds.lrecl, ksds.key_offset, ksds.key_length)
        case PathView() as path:
            return _Shape(path.base.lrecl, path.key_offset, path.key_length)
        case _:
            raise TypeError(f"{dataset.dsn} is neither a KSDS nor a path")


def _canonical(file_name: str) -> str:
    return file_name.upper().strip("'\"")


def _key(dataset: Dataset, key: bytes) -> bytes:
    return key[: _shape(dataset).key_length]


def _outcome(result: AccessResult) -> ReadOutcome:
    match result:
        case AccessResult(data=bytes() as record) if (
            result.condition in _RETURNS_RECORD
        ):
            return RecordRead(record, to_eibresp(result.condition))
        case _:
            return NoRecord(to_eibresp(result.condition))


def _missed(
    name: str, dataset: Dataset, key: bytes, condition: AccessCondition
) -> None:
    shape = _shape(dataset)
    if condition is not AccessCondition.NOT_FOUND or len(key) == shape.key_length:
        return
    logger.warning(
        "%s (%s): NOTFND; declared key %d bytes at offset %d, program key %d bytes",
        name,
        dataset.dsn,
        shape.key_length,
        shape.key_offset,
        len(key),
    )


def _sized(name: str, dataset: Dataset, record: bytes) -> None:
    shape = _shape(dataset)
    if len(record) == shape.lrecl:
        return
    logger.warning(
        "%s (%s): declared record length %d, program record %d bytes",
        name,
        dataset.dsn,
        shape.lrecl,
        len(record),
    )


def _record_key(dataset: Dataset, record: bytes) -> bytes:
    shape = _shape(dataset)
    return record[shape.key_offset : shape.key_offset + shape.key_length]


def _located(drv: FileOrganizationDriver, key: bytes, by: KeyMatch) -> AccessResult:
    positioned = drv.start(key, by.value)
    if positioned.condition is not AccessCondition.OK:
        return positioned
    return drv.read_seq()


def _keyed(
    dataset: Dataset, drv: FileOrganizationDriver, key: bytes, by: KeyMatch
) -> AccessResult:
    full = len(key) == _shape(dataset).key_length
    if full and by is KeyMatch.EQUAL:
        return drv.read_key(key)
    return _located(drv, key, by)


def _written(name: str, dataset: Dataset, record: bytes) -> int:
    _sized(name, dataset, record)
    drv = dataset.opened(OpenMode.IO)
    result = drv.write(record)
    drv.close()
    return to_eibresp(result.condition)


def _rewritten(name: str, dataset: Dataset, key: bytes, record: bytes) -> int:
    _sized(name, dataset, record)
    drv = dataset.opened(OpenMode.IO)
    result = drv.rewrite(record, _key(dataset, key))
    drv.close()
    return to_eibresp(result.condition)


class VsamEngine:
    """Imperative shell: CICS file control, each CICS file a cataloged dataset opened per operation; it keeps each file's held key and each open browse."""

    def __init__(self, files: Mapping[str, Dataset]) -> None:
        self._files = files
        self._held: Table[str, bytes] = Table()
        self._browse: Table[_CursorKey, FileOrganizationDriver] = Table()

    def _file(self, file_name: str) -> Dataset | _NoFile:
        name = _canonical(file_name)
        return self._files[name] if name in self._files else _NoFile()

    def key_length(self, file_name: str) -> int:
        match self._file(file_name):
            case Dataset() as dataset:
                return _shape(dataset).key_length
            case _NoFile():
                return 0

    def read(
        self, file_name: str, key: bytes, by: KeyMatch = KeyMatch.EQUAL
    ) -> ReadOutcome:
        match self._file(file_name):
            case Dataset() as dataset:
                return self._read(_canonical(file_name), dataset, key, by)
            case _NoFile():
                return NoRecord(RESP_DISABLED)

    def _read(
        self, name: str, dataset: Dataset, key: bytes, by: KeyMatch
    ) -> ReadOutcome:
        search = _key(dataset, key)
        drv = dataset.opened(OpenMode.INPUT)
        result = _keyed(dataset, drv, search, by)
        drv.close()
        _missed(name, dataset, search, result.condition)
        outcome = _outcome(result)
        self._hold(name, dataset, outcome)
        return outcome

    def _hold(self, name: str, dataset: Dataset, outcome: ReadOutcome) -> None:
        match outcome:
            case RecordRead(record=record):
                self._held.put(name, _record_key(dataset, record))
            case NoRecord():
                return

    def write(self, file_name: str, key: bytes, key_length: int, record: bytes) -> int:
        match self._file(file_name):
            case Dataset() as dataset:
                return _written(_canonical(file_name), dataset, record)
            case _NoFile():
                return RESP_DISABLED

    def rewrite(
        self, file_name: str, key: bytes, key_length: int, record: bytes
    ) -> int:
        match self._file(file_name):
            case Dataset() as dataset:
                return _rewritten(_canonical(file_name), dataset, key, record)
            case _NoFile():
                return RESP_DISABLED

    def delete(self, file_name: str, key: bytes) -> int:
        match self._file(file_name):
            case Dataset() as dataset:
                return self._delete(_canonical(file_name), dataset, key)
            case _NoFile():
                return RESP_DISABLED

    def _held_key(self, name: str) -> bytes:
        return self._held.get(name) if self._held.has(name) else b""

    def _delete(self, name: str, dataset: Dataset, key: bytes) -> int:
        match_key = _key(dataset, key) or self._held_key(name)
        if not match_key:
            return RESP_NOTFND
        drv = dataset.opened(OpenMode.IO)
        result = drv.delete(match_key)
        drv.close()
        _missed(name, dataset, match_key, result.condition)
        self._released(name, result.condition)
        return to_eibresp(result.condition)

    def _released(self, name: str, condition: AccessCondition) -> None:
        if condition in _RETURNS_RECORD and self._held.has(name):
            self._held.take(name)

    def startbr(
        self,
        file_name: str,
        key: bytes,
        cursor_key: _CursorKey,
        start: KeyMatch = KeyMatch.GTEQ,
    ) -> int:
        match self._file(file_name):
            case Dataset() as dataset:
                return self._startbr(
                    _canonical(file_name), dataset, key, cursor_key, start
                )
            case _NoFile():
                return RESP_DISABLED

    def _startbr(
        self,
        name: str,
        dataset: Dataset,
        key: bytes,
        cursor_key: _CursorKey,
        start: KeyMatch,
    ) -> int:
        search = _key(dataset, key)
        drv = dataset.opened(OpenMode.INPUT)
        result = drv.start(search, start.value)
        missed = result.condition is not AccessCondition.OK
        if missed and start is KeyMatch.EQUAL:
            _missed(name, dataset, search, result.condition)
            return RESP_NOTFND
        self._browse.put(cursor_key, drv)
        return RESP_NORMAL

    def resetbr(
        self,
        file_name: str,
        key: bytes,
        cursor_key: _CursorKey,
        start: KeyMatch = KeyMatch.GTEQ,
    ) -> int:
        if not self._browse.has(cursor_key):
            return RESP_INVREQ
        self._browse.take(cursor_key).close()
        return self.startbr(file_name, key, cursor_key, start)

    def readnext(self, file_name: str, cursor_key: _CursorKey) -> ReadOutcome:
        return _outcome(self._browse.get(cursor_key).read_seq())

    def readprev(self, file_name: str, cursor_key: _CursorKey) -> ReadOutcome:
        return _outcome(self._browse.get(cursor_key).read_prev())

    def endbr(self, file_name: str, cursor_key: _CursorKey) -> int:
        self._browse.take(cursor_key).close()
        return RESP_NORMAL
