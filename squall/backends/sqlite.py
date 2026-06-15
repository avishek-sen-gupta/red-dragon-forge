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
from decimal import Decimal

from squall.backend import SqlResult

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

    def execute(self, sql: str, params: list) -> SqlResult:
        try:
            cur = self._conn.execute(sql, params)
        except sqlite3.Error as exc:
            # SQLite has no DB2 SQLCODEs — report a generic failure (-1), but
            # never swallow the driver error silently.
            logger.warning("SQLite execute failed (sqlcode -1): %s | sql=%s", exc, sql)
            return SqlResult(rows=(), rowcount=0, sqlcode=-1)

        if cur.description is not None:
            # SELECT (or any statement that returns columns)
            rows = tuple(tuple(row) for row in cur.fetchall())
            sqlcode = 0 if rows else 100
            return SqlResult(rows=rows, rowcount=len(rows), sqlcode=sqlcode)
        else:
            # DML — commit and report affected rows
            self._conn.commit()
            return SqlResult(rows=(), rowcount=cur.rowcount, sqlcode=0)

    # ── Cursor API ────────────────────────────────────────────────────────────

    def open_cursor(self, name: str, sql: str, params: list) -> None:
        """Execute a SELECT and store the live cursor under *name*."""
        cur = self._conn.execute(sql, params)
        self._cursors[name] = cur

    def fetch(self, name: str) -> SqlResult:
        """Fetch one row from the named cursor."""
        cur = self._cursors.get(name)
        if cur is None:
            return SqlResult(rows=(), rowcount=0, sqlcode=100)
        row = cur.fetchone()
        if row is None:
            return SqlResult(rows=(), rowcount=0, sqlcode=100)
        return SqlResult(rows=(tuple(row),), rowcount=1, sqlcode=0)

    def close(self, name: str) -> None:
        """Close and drop the named cursor (no-op if absent)."""
        cur = self._cursors.pop(name, None)
        if cur is not None:
            cur.close()
