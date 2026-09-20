"""Task 10 (2026-09-19-carddemo-db2-tier): the CARDDEMO Db2 schema and seed
data red_dragon_forge.carddemo_db2_schema builds, verified against a LIVE
Db2 (container squall-db2, host port 15000 — see squall/.env and
tests/integration/db2_env.sh). No skip beyond db2_dsn's own (SQUALL_DB2_DSN
unset): once the DSN is present these fail loud, matching squall's own
test_db2_* convention.

Every assertion here reads through db2_probe_conn, a THIRD connection,
never db2_admin_conn (which did the seeding) and never a Db2Backend's own
connection — see conftest.py's db2_probe_conn docstring for why that
separation is the entire point of this suite.
"""

from __future__ import annotations

import ibm_db
import pytest

pytestmark = pytest.mark.usefixtures("carddemo_db2_schema")


def _rows(conn, sql: str) -> list[tuple]:
    # ibm_db's stub types exec_immediate()'s return as IBM_DBStatement | bool
    # (its C API can return False) even though it raises on failure in
    # practice (see squall.backends.db2's own docstring on this exact stub
    # boundary).
    stmt = ibm_db.exec_immediate(conn, sql)
    out = []
    row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    while row is not False:
        out.append(tuple(row))
        row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    return out


def test_seven_transaction_types_are_committed(db2_probe_conn):
    """Verified by execution: reads through db2_probe_conn, a connection
    that never performed the seed itself, so this can only pass if the
    insert was actually committed by db2_admin_conn (autocommit ON) — not
    merely visible on the seeding session."""
    rows = _rows(
        db2_probe_conn,
        "SELECT TR_TYPE, TR_DESCRIPTION FROM CARDDEMO.TRANSACTION_TYPE "
        "ORDER BY TR_TYPE",
    )
    assert len(rows) == 7


def test_reveral_misspelling_is_preserved_verbatim(db2_probe_conn):
    """Verified by execution. ctl/DB2LTTYP.ctl spells type 06 'REVERAL' (not
    'REVERSAL') — a corrected spelling here would mean the seed values were
    silently "fixed" rather than taken from the vendored file, exactly the
    drift task 10 rules against."""
    rows = _rows(
        db2_probe_conn,
        "SELECT TR_DESCRIPTION FROM CARDDEMO.TRANSACTION_TYPE WHERE TR_TYPE = '06'",
    )
    assert rows == [("REVERAL",)]


def test_eighteen_categories_are_committed(db2_probe_conn):
    """Verified by execution, same committed-vs-visible distinction as the
    transaction-type count above."""
    rows = _rows(
        db2_probe_conn, "SELECT COUNT(*) FROM CARDDEMO.TRANSACTION_TYPE_CATEGORY"
    )
    assert rows == [(18,)]


def test_category_foreign_key_rejects_an_unknown_parent_type(db2_probe_conn):
    """Verified by execution: proves TRNTYCAT.ddl's FOREIGN KEY clause was
    executed verbatim (not silently dropped), independent of
    XTRNTYCAT.ddl's skipped unique index — an insert referencing a
    TR_TYPE that was never seeded must fail with SQLSTATE 23503 (foreign
    key violation) specifically, not merely *some* exception -- a bare
    ``pytest.raises(Exception)`` would pass identically on a typo'd table
    or column name, which tests nothing about the constraint."""
    with pytest.raises(Exception) as excinfo:
        ibm_db.exec_immediate(
            db2_probe_conn,
            "INSERT INTO CARDDEMO.TRANSACTION_TYPE_CATEGORY "
            "(TRC_TYPE_CODE, TRC_TYPE_CATEGORY, TRC_CAT_DATA) "
            "VALUES ('99', '0001', 'NO SUCH PARENT TYPE')",
        )
    assert "SQLSTATE=23503" in str(excinfo.value)


def test_transaction_type_primary_key_rejects_a_duplicate(db2_probe_conn):
    """Verified by execution: TRNTYPE.ddl's PRIMARY KEY(TR_TYPE) is the
    equivalent unique constraint the ruling cites in place of the skipped
    XTRNTYPE.ddl (ERASE NO/CLOSE NO are z/OS-only, SQL0104N on Db2 LUW) —
    a duplicate TR_TYPE insert must fail with SQLSTATE 23505 (unique
    constraint violation) specifically, for the same reason as the FK
    check above."""
    with pytest.raises(Exception) as excinfo:
        ibm_db.exec_immediate(
            db2_probe_conn,
            "INSERT INTO CARDDEMO.TRANSACTION_TYPE (TR_TYPE, TR_DESCRIPTION) "
            "VALUES ('01', 'DUPLICATE')",
        )
    assert "SQLSTATE=23505" in str(excinfo.value)
