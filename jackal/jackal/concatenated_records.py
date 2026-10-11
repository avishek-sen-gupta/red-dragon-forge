"""A concatenation read as one sequential dataset: each member opened in turn, as z/OS reads sequentially concatenated data sets."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator, Sequence
from itertools import count, takewhile
from pathlib import Path

from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from interpreter.cobol.file_drivers import FileOrganizationDriver

MemberOpener = Callable[[], FileOrganizationDriver]

_END = AccessResult(AccessCondition.END_OF_FILE)
_READ_ONLY = AccessResult(AccessCondition.WRITE_NOT_PERMITTED)


def _member_records(open_member: MemberOpener) -> Iterator[AccessResult]:
    driver = open_member()
    try:
        reads = (driver.read_seq() for _ in count())
        yield from takewhile(lambda r: r.condition is not _END.condition, reads)
    finally:
        driver.close()


def _records(
    members: Sequence[MemberOpener],
) -> Generator[AccessResult, None, None]:
    for open_member in members:
        yield from _member_records(open_member)


class ConcatenatedDriver(FileOrganizationDriver):
    """Reads member after member; end of file comes only after the last member."""

    def __init__(self, members: Sequence[MemberOpener]) -> None:
        self._reads = _records(members)

    def open(
        self,
        path: Path,
        mode: OpenMode,
        record_length: int,
        key_offset: int,
        key_length: int,
    ) -> None:
        raise TypeError("a ConcatenatedDriver is opened when it is constructed")

    def close(self) -> None:
        self._reads.close()

    def read_seq(self) -> AccessResult:
        return next(self._reads, _END)

    def read_prev(self) -> AccessResult:
        raise NotImplementedError("concatenated data sets cannot be read backward")

    def read_key(self, key: bytes) -> AccessResult:
        return AccessResult(AccessCondition.NOT_FOUND)

    def start(self, key: bytes, relop: str) -> AccessResult:
        return AccessResult(AccessCondition.OK)

    def write(self, data: bytes, key: bytes = b"") -> AccessResult:
        return _READ_ONLY

    def rewrite(self, data: bytes, key: bytes = b"") -> AccessResult:
        return _READ_ONLY

    def delete(self, key: bytes = b"") -> AccessResult:
        return _READ_ONLY
