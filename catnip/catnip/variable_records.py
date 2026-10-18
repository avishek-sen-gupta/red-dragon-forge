"""A sequential dataset of variable-length records, each behind a 4-byte record descriptor word, as z/OS stores RECFM=V."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import accumulate, repeat, takewhile
from pathlib import Path
from typing import BinaryIO, Literal

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver
from interpreter.cobol.prime_key import PrimeKey

_RDW = 4
_FILE_MODES: Mapping[OpenMode, Literal["rb", "w+b", "a+b", "r+b"]] = {
    OpenMode.INPUT: "rb",
    OpenMode.OUTPUT: "w+b",
    OpenMode.EXTEND: "a+b",
    OpenMode.IO: "r+b",
}
_WRITE_MODES = frozenset({OpenMode.OUTPUT, OpenMode.EXTEND, OpenMode.IO})


def _rdw(data: bytes) -> bytes:
    return (len(data) + _RDW).to_bytes(2, "big") + bytes(2)


def _record_end(handle: BinaryIO, start: int) -> int:
    handle.seek(start)
    return start + int.from_bytes(handle.read(2), "big")


class VariableRecordDriver(FileOrganizationDriver):
    """Reads each record at its own length, padded to the reader's record area; a REWRITE keeps the length."""

    def __init__(self, path: Path, mode: OpenMode, area: int) -> None:
        self._handle: BinaryIO = open(path, _FILE_MODES[mode])  # noqa: SIM115
        self._mode = mode
        self._area = area

    def open(
        self,
        path: Path,
        mode: OpenMode,
        record_length: int,
        key: PrimeKey,
    ) -> None:
        raise TypeError("a VariableRecordDriver is opened when it is constructed")

    def close(self) -> None:
        self._handle.close()

    def read_seq(self) -> AccessResult:
        rdw = self._handle.read(_RDW)
        if not rdw:
            return AccessResult(AccessCondition.END_OF_FILE)
        data = self._handle.read(int.from_bytes(rdw[:2], "big") - _RDW)
        return AccessResult(AccessCondition.OK, data.ljust(self._area))

    def read_prev(self) -> AccessResult:
        raise NotImplementedError("sequential files do not support READ PREVIOUS")

    def read_key(self, key: bytes) -> AccessResult:
        return AccessResult(AccessCondition.NOT_FOUND)

    def start(self, key: bytes, relop: str) -> AccessResult:
        return AccessResult(AccessCondition.OK)

    def write(self, data: bytes, key: bytes = b"") -> AccessResult:
        if self._mode not in _WRITE_MODES:
            return AccessResult(AccessCondition.WRITE_NOT_PERMITTED)
        self._handle.seek(0, 2)
        self._handle.write(_rdw(data) + data)
        return AccessResult(AccessCondition.OK)

    def rewrite(self, data: bytes, key: bytes = b"") -> AccessResult:
        end = self._handle.tell()
        start = self._last_start(end)
        if end - start != len(data) + _RDW:
            self._handle.seek(end)
            return AccessResult(AccessCondition.BOUNDARY_VIOLATION)
        self._handle.seek(start)
        self._handle.write(_rdw(data) + data)
        return AccessResult(AccessCondition.OK)

    def delete(self, key: bytes = b"") -> AccessResult:
        return AccessResult(AccessCondition.OK)

    def _last_start(self, end: int) -> int:
        starts = accumulate(
            repeat(0), lambda start, _: _record_end(self._handle, start), initial=0
        )
        return max(takewhile(lambda start: start < end, starts))
