"""CICS file control over the system catalog's datasets: a cluster or a path per CICS file."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver

from cics.vsam.browse import BrowseStart
from cics.vsam.eibresp import RESP_DUPREC as RESP_DUPREC
from cics.vsam.eibresp import RESP_IOERR as RESP_IOERR
from cics.vsam.eibresp import (
    RESP_DISABLED,
    RESP_ENDFILE,
    RESP_NORMAL,
    RESP_NOTFND,
    to_eibresp,
)

logger = logging.getLogger(__name__)

_CursorKey = tuple[str, str, str]

_RETURNS_RECORD = frozenset({AccessCondition.OK, AccessCondition.DUPLICATES_FOLLOW})


@dataclass(frozen=True)
class _Shape:
    """A CICS file's record length and key position, as its catalog label declares them."""

    lrecl: int
    key_offset: int
    key_length: int


def _shape(dataset: Dataset) -> _Shape:
    match dataset.label:
        case KsdsLabel(lrecl=lrecl, key_offset=offset, key_length=length):
            return _Shape(lrecl, offset, length)
        case PathView(base=base, key_offset=offset, key_length=length):
            return _Shape(base.lrecl, offset, length)
        case _:
            raise TypeError(f"{dataset.dsn} is neither a KSDS nor a path")


def _canonical(file_name: str) -> str:
    return file_name.upper().strip("'\"")


def _record(result: AccessResult) -> tuple[bytes | None, int]:
    if result.condition in _RETURNS_RECORD:
        return result.data, to_eibresp(result.condition)
    return None, to_eibresp(result.condition)


class VsamEngine:
    """CICS file-control adapter: each CICS file is a cataloged dataset, opened per operation."""

    def __init__(self, files: Mapping[str, Dataset]) -> None:
        self._files = files
        self._held_key: dict[str, bytes] = {}
        self._browse: dict[_CursorKey, FileOrganizationDriver] = {}

    def _open(self, file_name: str, mode: OpenMode) -> FileOrganizationDriver | None:
        dataset = self._files.get(_canonical(file_name))
        if dataset is None:
            return None
        return dataset.opened(mode)

    def _missed(
        self, file_name: str, key_length: int, condition: AccessCondition
    ) -> None:
        name = _canonical(file_name)
        dataset = self._files[name]
        shape = _shape(dataset)
        if condition is not AccessCondition.NOT_FOUND:
            return
        if key_length == shape.key_length:
            return
        logger.warning(
            "%s (%s): NOTFND; declared key %d bytes at offset %d, program key %d bytes",
            name,
            dataset.dsn,
            shape.key_length,
            shape.key_offset,
            key_length,
        )

    def _sized(self, file_name: str, record: bytes) -> None:
        name = _canonical(file_name)
        dataset = self._files[name]
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

    def _key(self, file_name: str, key: bytes) -> bytes:
        return key[: _shape(self._files[_canonical(file_name)]).key_length]

    def read(
        self, file_name: str, key: bytes, key_length: int
    ) -> tuple[bytes | None, int]:
        drv = self._open(file_name, OpenMode.INPUT)
        if drv is None:
            return None, RESP_DISABLED
        search = self._key(file_name, key)
        result = drv.read_key(search)
        drv.close()
        self._missed(file_name, key_length, result.condition)
        if result.condition in _RETURNS_RECORD:
            self._held_key[_canonical(file_name)] = search
        return _record(result)

    def write(self, file_name: str, key: bytes, key_length: int, record: bytes) -> int:
        drv = self._open(file_name, OpenMode.IO)
        if drv is None:
            return RESP_DISABLED
        self._sized(file_name, record)
        result = drv.write(record)
        drv.close()
        return to_eibresp(result.condition)

    def rewrite(
        self, file_name: str, key: bytes, key_length: int, record: bytes
    ) -> int:
        drv = self._open(file_name, OpenMode.IO)
        if drv is None:
            return RESP_DISABLED
        self._sized(file_name, record)
        result = drv.rewrite(record, self._key(file_name, key))
        drv.close()
        return to_eibresp(result.condition)

    def delete(self, file_name: str, key: bytes, key_length: int) -> int:
        name = _canonical(file_name)
        if name not in self._files:
            return RESP_DISABLED
        match_key = self._key(file_name, key) or self._held_key.get(name, b"")
        if not match_key:
            return RESP_NOTFND
        drv = self._open(file_name, OpenMode.IO)
        assert drv is not None
        result = drv.delete(match_key)
        drv.close()
        self._missed(file_name, key_length, result.condition)
        if result.condition in _RETURNS_RECORD:
            self._held_key.pop(name, None)
        return to_eibresp(result.condition)

    def startbr(
        self,
        file_name: str,
        key: bytes,
        key_length: int,
        cursor_key: _CursorKey,
        start: BrowseStart = BrowseStart.GTEQ,
    ) -> int:
        drv = self._open(file_name, OpenMode.INPUT)
        if drv is None:
            return RESP_DISABLED
        result = drv.start(self._key(file_name, key), start.value)
        missed = result.condition is not AccessCondition.OK
        if missed and start is BrowseStart.EQUAL:
            self._missed(file_name, key_length, result.condition)
            return RESP_NOTFND
        self._browse[cursor_key] = drv
        return RESP_NORMAL

    def readnext(
        self, file_name: str, cursor_key: _CursorKey
    ) -> tuple[bytes | None, int]:
        return _record(self._browse[cursor_key].read_seq())

    def readprev(
        self, file_name: str, cursor_key: _CursorKey
    ) -> tuple[bytes | None, int]:
        return _record(self._browse[cursor_key].read_prev())

    def endbr(self, file_name: str, cursor_key: _CursorKey) -> int:
        self._browse.pop(cursor_key).close()
        return RESP_NORMAL
