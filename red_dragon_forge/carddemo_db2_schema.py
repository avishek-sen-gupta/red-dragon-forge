"""Db2 schema and seed data for CardDemo's transaction-type tier
(``app-transaction-type-db2``) -- task 10 of the 2026-09-19-carddemo-db2-tier
plan.

Two tables, ``CARDDEMO.TRANSACTION_TYPE`` (parent) and
``CARDDEMO.TRANSACTION_TYPE_CATEGORY`` (child, FK to the parent), created
from the vendored ``ddl/TRNTYPE.ddl`` / ``ddl/TRNTYCAT.ddl`` files verbatim so
the schema can never drift from what COTRTUPC/COTRTLIC expect.

**Ruling: ``ddl/XTRNTYPE.ddl`` and ``ddl/XTRNTYCAT.ddl`` are never executed.**
Both create a unique index with the ``ERASE NO`` / ``CLOSE NO`` DASD
attributes, which are z/OS-only syntax -- Db2 LUW rejects them with
SQL0104N ("unexpected token found"). Each table's own ``PRIMARY KEY`` clause
already creates an equivalent unique index, so skipping these two files loses
no constraint.

Seed values are taken from ``ctl/DB2LTTYP.ctl`` (7 transaction types) and
``ctl/DB2LTCAT.ctl`` (18 categories) but those files are never executed
directly -- both open with an Apache-licence header written as ``/* */``
comments and close with a bare ``COMMIT;``, and hand-rolling a splitter for
25 rows of SQL is not worth it. The vendored misspelling ``REVERAL`` (type
``06``) is preserved verbatim.
"""

from __future__ import annotations

from pathlib import Path

import ibm_db

_SCHEMA = "CARDDEMO"

# ctl/DB2LTTYP.ctl, in file order.
TRANSACTION_TYPES: tuple[tuple[str, str], ...] = (
    ("01", "PURCHASE"),
    ("02", "PAYMENT"),
    ("03", "CREDIT"),
    ("04", "AUTHORIZATION"),
    ("05", "REFUND"),
    ("06", "REVERAL"),  # vendored misspelling, preserved verbatim
    ("07", "ADJUSTMENT"),
)

# ctl/DB2LTCAT.ctl, in file order: (TRC_TYPE_CODE, TRC_TYPE_CATEGORY, TRC_CAT_DATA).
TRANSACTION_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("01", "0001", "REGULAR SALES DRAFT"),
    ("01", "0002", "REGULAR CASH ADVANCE"),
    ("01", "0003", "CONVENIENCE CHECK DEBIT"),
    ("01", "0004", "ATM CASH ADVANCE"),
    ("01", "0005", "INTEREST AMOUNT"),
    ("02", "0001", "CASH PAYMENT"),
    ("02", "0002", "ELECTRONIC PAYMENT"),
    ("02", "0003", "CHECK PAYMENT"),
    ("03", "0001", "CREDIT TO ACCOUNT"),
    ("03", "0002", "CREDIT TO PURCHASE BALANCE"),
    ("03", "0003", "CREDIT TO CASH BALANCE"),
    ("04", "0001", "ZERO DOLLAR AUTHORIZATION"),
    ("04", "0002", "ONLINE PURCHASE AUTHORIZATION"),
    ("04", "0003", "TRAVEL BOOKING AUTHORIZATION"),
    ("05", "0001", "REFUND CREDIT"),
    ("06", "0001", "FRAUD REVERSAL"),
    ("06", "0002", "NON FRAUD REVERSAL"),
    ("07", "0001", "SALES DRAFT CREDIT ADJUSTMENT"),
)


def _run_tolerating(conn, sql: str, tolerated_sqlstate: str) -> None:
    """Run *sql* for its idempotent side effect, swallowing failure ONLY when
    it carries *tolerated_sqlstate* -- the "already in the desired state"
    case this idempotent setup step expects (object-already-exists on
    CREATE SCHEMA, undefined-name on a DROP TABLE with nothing to drop).
    ibm_db raises a bare Exception (no narrower public class -- see
    squall.backends.db2's own docstring on the same boundary) whose message
    embeds the real ``SQLSTATE=nnnnn``; any OTHER failure (a lock wait, a
    permission error, a typo) is a real problem for a setup routine and must
    propagate rather than be swallowed -- a blanket ``except Exception: pass``
    here would hide exactly the kind of failure that leaves stale rows for
    the seed step to collide with."""
    try:
        ibm_db.exec_immediate(conn, sql)
    except Exception as exc:
        if f"SQLSTATE={tolerated_sqlstate}" not in str(exc):
            raise


_ALREADY_EXISTS = "42710"  # CREATE SCHEMA on a schema that already exists.
_UNDEFINED_NAME = "42704"  # DROP TABLE on a table that doesn't exist yet.


def drop_tables(conn) -> None:
    """Drop both tables if present, child before parent -- TRANSACTION_TYPE
    carries a FOREIGN KEY reference from TRANSACTION_TYPE_CATEGORY, so Db2
    refuses to drop the parent first."""
    _run_tolerating(
        conn, f"DROP TABLE {_SCHEMA}.TRANSACTION_TYPE_CATEGORY", _UNDEFINED_NAME
    )
    _run_tolerating(conn, f"DROP TABLE {_SCHEMA}.TRANSACTION_TYPE", _UNDEFINED_NAME)


def create_schema(conn) -> None:
    _run_tolerating(conn, f"CREATE SCHEMA {_SCHEMA}", _ALREADY_EXISTS)


def create_tables(conn, db2_tree: Path) -> None:
    """Execute ``ddl/TRNTYPE.ddl`` then ``ddl/TRNTYCAT.ddl`` verbatim --
    parent before child, since TRNTYCAT.ddl's FOREIGN KEY clause requires
    TRANSACTION_TYPE to already exist."""
    ddl_dir = db2_tree / "ddl"
    for name in ("TRNTYPE.ddl", "TRNTYCAT.ddl"):
        ibm_db.exec_immediate(conn, (ddl_dir / name).read_text(encoding="utf-8"))


def _insert(conn, sql: str, params: tuple) -> None:
    # ibm_db's stub types prepare()'s return as IBM_DBStatement | bool (its C
    # API can return False) even though it raises on any failure in practice
    # (see squall.backends.db2's own docstring on this exact stub boundary).
    stmt = ibm_db.prepare(conn, sql)
    ibm_db.execute(stmt, params)  # type: ignore[reportArgumentType]


def seed(conn) -> None:
    """Insert the 7 transaction types, then the 18 categories -- parents
    before children, matching create_tables' FK-respecting order."""
    for tr_type, description in TRANSACTION_TYPES:
        _insert(
            conn,
            f"INSERT INTO {_SCHEMA}.TRANSACTION_TYPE "
            "(TR_TYPE, TR_DESCRIPTION) VALUES (?, ?)",
            (tr_type, description),
        )
    for type_code, category, data in TRANSACTION_CATEGORIES:
        _insert(
            conn,
            f"INSERT INTO {_SCHEMA}.TRANSACTION_TYPE_CATEGORY "
            "(TRC_TYPE_CODE, TRC_TYPE_CATEGORY, TRC_CAT_DATA) VALUES (?, ?, ?)",
            (type_code, category, data),
        )


def apply_schema(conn, db2_tree: Path) -> None:
    """Full idempotent setup against *conn*: drop any prior run's tables,
    (re)create the CARDDEMO schema and both tables from the vendored DDL,
    then seed both tables. The caller is responsible for committing (or
    running this over an autocommit-on connection) -- see this module's
    docstring and the ``db2_admin_conn`` fixture: seeding must be committed
    before a program-under-test's ``Db2Backend`` is constructed, since its
    ``__init__`` flips the connection it is given to
    ``SQL_AUTOCOMMIT_OFF``.
    """
    drop_tables(conn)
    create_schema(conn)
    create_tables(conn, db2_tree)
    seed(conn)
