"""
squall.backends.sqlite
~~~~~~~~~~~~~~~~~~~~~~
SQLite implementation of the ``SqlBackend`` protocol.

Design:
* Constructed over a ``sqlite3.Connection`` (the one mutable boundary).
* ``_cursors`` is the only mutable state: a dict mapping cursor name to
  an open ``sqlite3.Cursor``.  All other methods are effectively pure
  given a fixed connection.
* sqlcode semantics:
    0    — success
    100  — no rows / end-of-cursor  (SQL standard NOT FOUND / +100)
    -1   — any ``sqlite3.Error``
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from decimal import Decimal

from squall.backend import SqlResult
from squall.backends._stores import set_cursor

logger = logging.getLogger(__name__)

# Register a SQLite adapter so that Decimal values (produced by COMP-3 host-var
# decoding) can be passed as query parameters without a TypeError.
# The adapter converts Decimal → str; SQLite then coerces to NUMERIC as needed.
sqlite3.register_adapter(Decimal, str)


class SqliteBackend:
    """SQLite-backed SQL execution engine."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cursors: dict[str, sqlite3.Cursor] = {}

    # ── Core execute ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: Sequence) -> SqlResult:
        try:
            cur = self._conn.execute(sql, params)
        except sqlite3.Error as exc:
            # SQLite has no DB2 SQLCODEs — report a generic failure (-1), but
            # never swallow the driver error silently.
            logger.warning("SQLite execute failed (sqlcode -1): %s | sql=%s", exc, sql)
            return SqlResult(rows=(), rowcount=0, sqlcode=-1, sqlerrm=str(exc))

        match cur.description:
            case None:
                # DML — report affected rows. The transaction stays OPEN until
                # an explicit EXEC SQL COMMIT / ROLLBACK; DML is not
                # auto-committed.
                return SqlResult(rows=(), rowcount=cur.rowcount, sqlcode=0)
            case _:
                # SELECT (or any statement that returns columns)
                rows = tuple(tuple(row) for row in cur.fetchall())
                sqlcode = 0 if rows else 100
                return SqlResult(rows=rows, rowcount=len(rows), sqlcode=sqlcode)

    # ── Transaction control ──────────────────────────────────────────────────

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    # ── Cursor API ────────────────────────────────────────────────────────────

    def open_cursor(self, name: str, sql: str, params: Sequence) -> int:
        """Execute a SELECT and store the live cursor under *name*.

        Same error boundary as ``execute``: a ``sqlite3.Error`` is reported as
        SQLCODE -1, never raised.
        """
        try:
            cur = self._conn.execute(sql, params)
        except sqlite3.Error as exc:
            logger.warning(
                "SQLite open_cursor failed (sqlcode -1): %s | sql=%s", exc, sql
            )
            return -1
        set_cursor(self._cursors, name, cur)
        return 0

    def fetch(self, name: str) -> SqlResult:
        """Fetch one row from the named cursor."""
        match self._cursors.get(name):
            case None:
                return SqlResult(rows=(), rowcount=0, sqlcode=100)
            case cur:
                match cur.fetchone():
                    case None:
                        return SqlResult(rows=(), rowcount=0, sqlcode=100)
                    case row:
                        return SqlResult(rows=(tuple(row),), rowcount=1, sqlcode=0)

    def close(self, name: str) -> None:
        """Close and drop the named cursor (no-op if absent)."""
        match self._cursors.pop(name, None):
            case None:
                return
            case cur:
                cur.close()
