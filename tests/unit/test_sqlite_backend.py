"""
tests/unit/test_sqlite_backend.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TDD tests for Task 5 (SqlResult / SqlBackend protocol) and
Task 6 (SqliteBackend over an in-memory SQLite database).
"""

from __future__ import annotations

import sqlite3
from dataclasses import fields

import pytest

# ── Task 5: SqlResult + SqlBackend protocol ───────────────────────────────────


def test_sql_result_frozen():
    from squall.backend import SqlResult

    r = SqlResult(rows=((1,),), rowcount=1, sqlcode=0)
    with pytest.raises((TypeError, AttributeError)):
        r.sqlcode = 99  # type: ignore[misc]


def test_sql_result_fields():
    from squall.backend import SqlResult

    r = SqlResult(rows=((42, "foo"),), rowcount=1, sqlcode=0)
    assert r.rows == ((42, "foo"),)
    assert r.rowcount == 1
    assert r.sqlcode == 0


def test_sql_result_rows_is_tuple_of_tuples():
    from squall.backend import SqlResult

    r = SqlResult(rows=((1,), (2,)), rowcount=2, sqlcode=0)
    assert isinstance(r.rows, tuple)
    assert all(isinstance(row, tuple) for row in r.rows)


def test_sql_result_default_empty_dml():
    """DML convention: rows=(), rowcount=affected, sqlcode=0."""
    from squall.backend import SqlResult

    r = SqlResult(rows=(), rowcount=3, sqlcode=0)
    assert r.rows == ()
    assert r.rowcount == 3


def test_sqlcode_not_found():
    from squall.backend import SqlResult

    r = SqlResult(rows=(), rowcount=0, sqlcode=100)
    assert r.sqlcode == 100


def test_sqlcode_error_negative():
    from squall.backend import SqlResult

    r = SqlResult(rows=(), rowcount=0, sqlcode=-1)
    assert r.sqlcode < 0


def test_sql_backend_protocol_isinstance():
    """A class that has the four required methods satisfies SqlBackend."""
    from squall.backend import SqlBackend, SqlResult

    class FakeBackend:
        def execute(self, sql: str, params: list) -> SqlResult:
            return SqlResult(rows=(), rowcount=0, sqlcode=0)

        def open_cursor(self, name: str, sql: str, params: list) -> None:
            pass

        def fetch(self, name: str) -> SqlResult:
            return SqlResult(rows=(), rowcount=0, sqlcode=100)

        def close(self, name: str) -> None:
            pass

    assert isinstance(FakeBackend(), SqlBackend)


def test_sql_backend_protocol_missing_method_not_isinstance():
    """A class missing a method does NOT satisfy the protocol."""
    from squall.backend import SqlBackend

    class Incomplete:
        def execute(self, sql: str, params: list):
            pass

        # open_cursor / fetch / close missing

    assert not isinstance(Incomplete(), SqlBackend)


# ── Fixture: seeded in-memory SQLite database ─────────────────────────────────


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE ACCOUNT(ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    c.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
    c.execute("INSERT INTO ACCOUNT VALUES (22, 750)")
    c.commit()
    yield c
    c.close()


@pytest.fixture
def backend(conn):
    from squall.backends.sqlite import SqliteBackend

    return SqliteBackend(conn)


# ── Task 6: SqliteBackend — SELECT ────────────────────────────────────────────


def test_select_hit(backend):
    result = backend.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [11])
    assert result.rows == ((500,),)
    assert result.sqlcode == 0
    assert result.rowcount == 1


def test_select_no_row(backend):
    result = backend.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [99])
    assert result.rows == ()
    assert result.sqlcode == 100


def test_select_multiple_rows(backend):
    result = backend.execute("SELECT ACCT_ID FROM ACCOUNT ORDER BY ACCT_ID", [])
    assert result.rows == ((11,), (22,))
    assert result.sqlcode == 0
    assert result.rowcount == 2


def test_bad_sql_returns_negative_sqlcode(backend):
    result = backend.execute("SELECT nope FROM nope", [])
    assert result.sqlcode < 0
    assert result.rows == ()
    assert result.rowcount == 0


# ── Task 6: SqliteBackend — DML ───────────────────────────────────────────────


def test_insert_via_execute(backend):
    result = backend.execute("INSERT INTO ACCOUNT VALUES (?, ?)", [33, 1000])
    assert result.sqlcode == 0
    assert result.rowcount == 1
    # Verify persistence
    check = backend.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [33])
    assert check.rows == ((1000,),)


def test_update_via_execute(backend):
    result = backend.execute(
        "UPDATE ACCOUNT SET ACCT_BAL = ? WHERE ACCT_ID = ?", [999, 11]
    )
    assert result.sqlcode == 0
    assert result.rowcount == 1
    check = backend.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [11])
    assert check.rows == ((999,),)


def test_update_multiple_rows(backend):
    result = backend.execute("UPDATE ACCOUNT SET ACCT_BAL = ?", [0])
    assert result.sqlcode == 0
    assert result.rowcount == 2


# ── Task 6: SqliteBackend — cursor API ───────────────────────────────────────


def test_cursor_fetch_sequence(backend):
    backend.open_cursor("c", "SELECT ACCT_ID FROM ACCOUNT ORDER BY ACCT_ID", [])
    r1 = backend.fetch("c")
    assert r1.rows == ((11,),)
    assert r1.sqlcode == 0
    assert r1.rowcount == 1

    r2 = backend.fetch("c")
    assert r2.rows == ((22,),)
    assert r2.sqlcode == 0

    r3 = backend.fetch("c")
    assert r3.sqlcode == 100  # end of cursor
    assert r3.rows == ()


def test_cursor_close(backend):
    backend.open_cursor("c", "SELECT ACCT_ID FROM ACCOUNT ORDER BY ACCT_ID", [])
    backend.close("c")
    # Fetching a closed cursor should return end-of-cursor (100), not raise
    r = backend.fetch("c")
    assert r.sqlcode == 100


def test_cursor_close_nonexistent_noop(backend):
    # Closing a cursor that was never opened should not raise
    backend.close("does_not_exist")


def test_two_independent_cursors(backend):
    backend.open_cursor("a", "SELECT ACCT_ID FROM ACCOUNT ORDER BY ACCT_ID", [])
    backend.open_cursor("b", "SELECT ACCT_BAL FROM ACCOUNT ORDER BY ACCT_ID", [])

    a1 = backend.fetch("a")
    b1 = backend.fetch("b")

    assert a1.rows == ((11,),)
    assert b1.rows == ((500,),)

    backend.close("a")
    backend.close("b")


def test_sqlite_backend_satisfies_protocol(backend):
    from squall.backend import SqlBackend

    assert isinstance(backend, SqlBackend)
