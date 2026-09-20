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
from collections.abc import Sequence
from decimal import Decimal

import ibm_db
from squall.backend import SqlResult
from squall.backends._stores import set_cursor

logger = logging.getLogger(__name__)


def _last_sqlcode() -> int:
    """The numeric SQLCODE of the most recent ibm_db operation.

    The raw ibm_db driver exposes no numeric SQLCODE accessor; ``get_sqlcode()``
    returns the fixed-format ``'SQLCODE=<n>'`` string. Parse the trailing integer
    — failing loudly if the driver ever changes that contract, rather than
    masking a real DB2 code behind a generic -1.
    """
    return int(ibm_db.get_sqlcode().rsplit("=", 1)[1])


def _marshal(params: Sequence) -> tuple:
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
        # Faithful embedded-SQL transaction control: the program owns COMMIT /
        # ROLLBACK, so disable the driver's per-statement autocommit. Without this
        # a ROLLBACK would be a no-op (each statement already committed).
        ibm_db.autocommit(conn, ibm_db.SQL_AUTOCOMMIT_OFF)

    # ── Core execute ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: Sequence) -> SqlResult:
        # Marshal OUTSIDE the try: a bug in our own code must fail loud, not be
        # masked as a DB error. Only ibm_db's prepare/execute sit on the DB-error
        # boundary (ibm_db raises on any SQL failure; prepare defers to execute).
        marshalled = _marshal(params)
        # DB-error boundary: ibm_db raises a bare Exception (no narrower public
        # class), so catch broadly — only ibm_db prepare/execute are in scope.
        # The error becomes the SQL channel's real DB2 SQLCODE (e.g. -204), logged
        # rather than silently swallowed.
        try:
            # ibm_db's stub types prepare()'s return as IBM_DBStatement | bool
            # (its C API can return False) even though this codebase's own
            # contract is "ibm_db raises on any SQL failure" (see the class
            # docstring) — prepare/execute either succeed or raise, they never
            # return False here, so a `bool` result is unreachable in practice.
            stmt = ibm_db.prepare(self._conn, sql)
            ibm_db.execute(stmt, marshalled)  # type: ignore[reportArgumentType]
        except Exception as exc:  # noqa: BLE001
            sqlcode = _last_sqlcode()
            logger.warning(
                "Db2 execute failed (sqlcode %d): %s | sql=%s", sqlcode, exc, sql
            )
            return SqlResult(rows=(), rowcount=0, sqlcode=sqlcode, sqlerrm=str(exc))

        if ibm_db.num_fields(stmt):  # type: ignore[reportArgumentType]
            # Result-set statement (SELECT): drain rows; 100 if empty.
            rows = _drain(stmt)
            return SqlResult(rows=rows, rowcount=len(rows), sqlcode=0 if rows else 100)
        # DML — affected-row count.
        return SqlResult(
            rows=(), rowcount=ibm_db.num_rows(stmt), sqlcode=0  # type: ignore[reportArgumentType]
        )

    # ── Cursor API ────────────────────────────────────────────────────────────

    def open_cursor(self, name: str, sql: str, params: Sequence) -> int:
        # Same error boundary as ``execute``: a prepare/execute failure becomes
        # the real DB2 SQLCODE, logged, never raised.
        try:
            stmt = ibm_db.prepare(self._conn, sql)
            ibm_db.execute(stmt, _marshal(params))  # type: ignore[reportArgumentType]
        except Exception as exc:  # noqa: BLE001
            sqlcode = _last_sqlcode()
            logger.warning(
                "Db2 open_cursor failed (sqlcode %d): %s | sql=%s", sqlcode, exc, sql
            )
            return sqlcode
        set_cursor(self._cursors, name, stmt)
        return 0

    def fetch(self, name: str) -> SqlResult:
        match self._cursors.get(name):
            case None:
                return SqlResult(rows=(), rowcount=0, sqlcode=100)
            case stmt:
                row = ibm_db.fetch_tuple(stmt)
                if row is False:
                    return SqlResult(rows=(), rowcount=0, sqlcode=100)
                return SqlResult(rows=(tuple(row),), rowcount=1, sqlcode=0)

    def close(self, name: str) -> None:
        match self._cursors.pop(name, None):
            case None:
                return
            case stmt:
                ibm_db.free_result(stmt)

    # ── Transaction control ──────────────────────────────────────────────────

    def commit(self) -> None:
        ibm_db.commit(self._conn)

    def rollback(self) -> None:
        ibm_db.rollback(self._conn)
