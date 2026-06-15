"""
squall.backend
~~~~~~~~~~~~~~
Public protocol and result type for SQL backends.

Design:
* ``SqlResult`` is a frozen dataclass (immutability tenet).
* ``SqlBackend`` is a ``@runtime_checkable`` Protocol so that any class
  with the four required methods satisfies ``isinstance`` checks without
  subclassing.
* No global mutable state; the mutable ``sqlite3.Connection`` lives
  inside ``SqliteBackend``, the one permitted mutable boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SqlResult:
    rows: tuple[tuple, ...]  # result rows (SELECT/FETCH); () for DML
    rowcount: int  # affected rows (DML); len(rows) for SELECT
    sqlcode: int  # 0 ok, +100 not found / end-of-cursor, negative on error


@runtime_checkable
class SqlBackend(Protocol):
    def execute(self, sql: str, params: list) -> SqlResult: ...

    # Cursors are first-class EXEC SQL, so the protocol carries them from the start.
    def open_cursor(self, name: str, sql: str, params: list) -> None: ...

    def fetch(self, name: str) -> SqlResult: ...

    def close(self, name: str) -> None: ...
