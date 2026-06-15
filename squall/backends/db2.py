"""
squall.backends.db2
~~~~~~~~~~~~~~~~~~~
IBM Db2 implementation of the ``SqlBackend`` protocol, over the ``ibm_db``
driver. Same contract as ``SqliteBackend`` — squall lowers EXEC SQL to the
protocol, so swapping SQLite for real Db2 is just swapping the backend.

Design:
* Constructed over an open ``ibm_db`` connection (the one mutable boundary).
* ``_cursors`` maps a cursor name to a prepared+executed ``ibm_db`` statement.
* sqlcode semantics:
    0    — success
    100  — no rows / end-of-cursor
    <0   — the real DB2 SQLCODE for the failure (e.g. -204), via get_sqlcode();
           the program's `IF SQLCODE` logic then sees the actual code.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import ibm_db

from squall.backend import SqlResult

logger = logging.getLogger(__name__)


def _last_sqlcode() -> int:
    """The numeric SQLCODE of the most recent ibm_db operation.

    The raw ibm_db driver exposes no numeric SQLCODE accessor; ``get_sqlcode()``
    returns the fixed-format ``'SQLCODE=<n>'`` string. Parse the trailing integer
    — failing loudly if the driver ever changes that contract, rather than
    masking a real DB2 code behind a generic -1.
    """
    return int(ibm_db.get_sqlcode().rsplit("=", 1)[1])


def _marshal(params: list) -> tuple:
    """Marshal Python param values for ibm_db.

    ibm_db binds ints/strs/floats directly; Decimal is sent as its string form
    (Db2 coerces to DECIMAL), mirroring the SQLite Decimal adapter.
    """
    return tuple(str(p) if isinstance(p, Decimal) else p for p in params)


def _drain(stmt) -> tuple:
    """Fetch every remaining row of *stmt* as a tuple of tuples.

    ``iter(callable, sentinel)`` drives the fetch loop without a reassigned
    accumulator: it calls ``fetch_tuple`` until it returns the ``False`` sentinel.
    """
    return tuple(tuple(row) for row in iter(lambda: ibm_db.fetch_tuple(stmt), False))


class Db2Backend:
    """Db2-backed SQL execution engine (ibm_db)."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self._cursors: dict = {}

    # ── Core execute ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: list) -> SqlResult:
        # Marshal OUTSIDE the try: a bug in our own code must fail loud, not be
        # masked as a DB error. Only ibm_db's prepare/execute sit on the DB-error
        # boundary (ibm_db raises on any SQL failure; prepare defers to execute).
        marshalled = _marshal(params)
        # DB-error boundary: ibm_db raises a bare Exception (no narrower public
        # class), so catch broadly — only ibm_db prepare/execute are in scope.
        # The error becomes the SQL channel's real DB2 SQLCODE (e.g. -204), logged
        # rather than silently swallowed.
        try:
            stmt = ibm_db.prepare(self._conn, sql)
            ibm_db.execute(stmt, marshalled)
        except Exception as exc:  # noqa: BLE001
            sqlcode = _last_sqlcode()
            logger.warning(
                "Db2 execute failed (sqlcode %d): %s | sql=%s", sqlcode, exc, sql
            )
            return SqlResult(rows=(), rowcount=0, sqlcode=sqlcode)

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
