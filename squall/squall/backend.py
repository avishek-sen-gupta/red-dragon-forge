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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SqlResult:
    rows: tuple[tuple, ...]  # result rows (SELECT/FETCH); () for DML
    rowcount: int  # affected rows (DML); len(rows) for SELECT
    sqlcode: int  # 0 ok, +100 not found / end-of-cursor, negative on error
    # The driver's own error text (empty on success). Carried through to
    # SQLCA's SQLERRM by the binding engine — see squall.binding.write_sqlcode.
    sqlerrm: str = ""


@runtime_checkable
class SqlBackend(Protocol):
    def execute(self, sql: str, params: Sequence) -> SqlResult: ...

    # Cursors are first-class EXEC SQL, so the protocol carries them from the start.
    # Returns the SQLCODE (0 on success, negative on a DB error) — the same error
    # boundary as ``execute``: a DB failure preparing/running the cursor's SELECT
    # is reported, never raised.
    def open_cursor(self, name: str, sql: str, params: Sequence) -> int: ...

    def fetch(self, name: str) -> SqlResult: ...

    def close(self, name: str) -> None: ...

    # Transaction control. EXEC SQL COMMIT / ROLLBACK map to these directly; DML
    # is NOT auto-committed, so a unit of work spans statements until one is called.
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
