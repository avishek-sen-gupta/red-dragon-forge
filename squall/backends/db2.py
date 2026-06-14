"""
squall.backends.db2
~~~~~~~~~~~~~~~~~~~
IBM Db2 implementation of the ``SqlBackend`` protocol, over the ``ibm_db``
driver. Same contract as ``SqliteBackend`` — squall lowers EXEC SQL to the
protocol, so swapping SQLite for real Db2 is just swapping the backend.

Design:
* Constructed over an open ``ibm_db`` connection (the one mutable boundary).
* ``_cursors`` maps a cursor name to a prepared+executed ``ibm_db`` statement.
* sqlcode semantics match SqliteBackend:
    0    — success
    100  — no rows / end-of-cursor
    -1   — any driver error
"""

from __future__ import annotations

from decimal import Decimal

import ibm_db

from squall.backend import SqlResult


def _marshal(params: list) -> tuple:
    """Marshal Python param values for ibm_db.

    ibm_db binds ints/strs/floats directly; Decimal is sent as its string form
    (Db2 coerces to DECIMAL), mirroring the SQLite Decimal adapter.
    """
    return tuple(str(p) if isinstance(p, Decimal) else p for p in params)


def _drain(stmt) -> tuple:
    """Fetch every remaining row of *stmt* as a tuple of tuples."""
    rows = []
    row = ibm_db.fetch_tuple(stmt)
    while row is not False:
        rows.append(tuple(row))
        row = ibm_db.fetch_tuple(stmt)
    return tuple(rows)


class Db2Backend:
    """Db2-backed SQL execution engine (ibm_db)."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self._cursors: dict = {}

    # ── Core execute ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: list) -> SqlResult:
        try:
            stmt = ibm_db.prepare(self._conn, sql)
            if not ibm_db.execute(stmt, _marshal(params)):
                return SqlResult(rows=(), rowcount=0, sqlcode=-1)
        except Exception:
            return SqlResult(rows=(), rowcount=0, sqlcode=-1)

        if ibm_db.num_fields(stmt):
            # Result-set statement (SELECT): drain rows; 100 if empty.
            rows = _drain(stmt)
            return SqlResult(rows=rows, rowcount=len(rows), sqlcode=0 if rows else 100)
        # DML — affected-row count.
        return SqlResult(rows=(), rowcount=ibm_db.num_rows(stmt), sqlcode=0)

    # ── Cursor API ────────────────────────────────────────────────────────────

    def open_cursor(self, name: str, sql: str, params: list) -> None:
        stmt = ibm_db.prepare(self._conn, sql)
        ibm_db.execute(stmt, _marshal(params))
        self._cursors[name] = stmt

    def fetch(self, name: str) -> SqlResult:
        stmt = self._cursors.get(name)
        if stmt is None:
            return SqlResult(rows=(), rowcount=0, sqlcode=100)
        row = ibm_db.fetch_tuple(stmt)
        if row is False:
            return SqlResult(rows=(), rowcount=0, sqlcode=100)
        return SqlResult(rows=(tuple(row),), rowcount=1, sqlcode=0)

    def close(self, name: str) -> None:
        stmt = self._cursors.pop(name, None)
        if stmt is not None:
            ibm_db.free_result(stmt)
