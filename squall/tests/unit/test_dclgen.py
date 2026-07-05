"""
tests/unit/test_dclgen.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
squall-side DCLGEN: a SQLite table schema → host-var copybook + JSON metadata.
v1 supports the categories the codec already binds (binary / COMP-3 / CHAR);
VARCHAR / float / lengthless TEXT raise rather than silently degrade.
"""

from __future__ import annotations

import sqlite3

import pytest

from squall.dclgen import (
    _cobolify,
    _parse_sql_type,
    generate,
)

# ── Name mapping ──────────────────────────────────────────────────────────────


def test_cobolify_underscore_to_hyphen_upper() -> None:
    assert _cobolify("ACCT_ID") == "ACCT-ID"
    assert _cobolify("acct_bal") == "ACCT-BAL"
    assert _cobolify("NAME") == "NAME"


# ── Declared-type → COBOL mapping ─────────────────────────────────────────────


def test_integer_maps_to_binary() -> None:
    t = _parse_sql_type("INTEGER")
    assert t["category"] == "BINARY"
    assert t["total_digits"] == 9 and t["decimal_digits"] == 0
    assert t["pic"] == "S9(9) COMP"
    assert t["sql_type"] == "INTEGER"


def test_smallint_and_bigint() -> None:
    assert _parse_sql_type("SMALLINT")["pic"] == "S9(4) COMP"
    assert _parse_sql_type("BIGINT")["pic"] == "S9(18) COMP"


def test_decimal_maps_to_comp3_scaled() -> None:
    t = _parse_sql_type("DECIMAL(7,2)")
    assert t["category"] == "COMP3"
    assert t["total_digits"] == 7 and t["decimal_digits"] == 2
    assert t["pic"] == "S9(5)V9(2) COMP-3"
    assert t["sql_type"] == "DECIMAL(7,2)"


def test_decimal_zero_scale() -> None:
    t = _parse_sql_type("NUMERIC(5,0)")
    assert t["pic"] == "S9(5) COMP-3"


def test_char_maps_to_alphanumeric() -> None:
    t = _parse_sql_type("CHAR(20)")
    assert t["category"] == "ALPHANUMERIC"
    assert t["length"] == 20
    assert t["pic"] == "X(20)"
    assert t["sql_type"] == "CHAR(20)"


@pytest.mark.parametrize("decl", ["TEXT", "REAL", "DOUBLE", "BLOB"])
def test_unsupported_types_raise(decl: str) -> None:
    with pytest.raises(NotImplementedError):
        _parse_sql_type(decl)


def test_varchar_maps_to_49_group() -> None:
    t = _parse_sql_type("VARCHAR(9)")
    assert t["category"] == "VARCHAR"
    assert t["length"] == 9
    assert t["sql_type"] == "VARCHAR(9)"
    # A VARCHAR is a GROUP (49-level LEN + TEXT children), not an elementary
    # item — it has no single PIC of its own.
    assert t["pic"] is None


# ── Full generation ───────────────────────────────────────────────────────────


def _seed() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ACCOUNT ("
        " ACCT_ID INTEGER NOT NULL,"
        " ACCT_BAL DECIMAL(7,2),"
        " ACCT_NAME CHAR(20))"
    )
    return conn


def test_generate_copybook_lines() -> None:
    rec = generate(_seed(), "ACCOUNT", record_name="ACCT-REC")
    cpy = rec.copybook
    assert "       01  ACCT-REC." in cpy
    assert "05  ACCT-ID" in cpy and "PIC S9(9) COMP." in cpy
    assert "05  ACCT-BAL" in cpy and "PIC S9(5)V9(2) COMP-3." in cpy
    assert "05  ACCT-NAME" in cpy and "PIC X(20)." in cpy
    # 01 in Area A (col 8), 05 in Area B (col 12)
    for line in cpy.splitlines():
        if "01  ACCT-REC" in line:
            assert line.index("01") == 7
        if "05  ACCT-ID" in line:
            assert line.index("05") == 11


def test_generate_metadata() -> None:
    rec = generate(_seed(), "ACCOUNT", record_name="ACCT-REC")
    md = rec.metadata
    assert md["record"] == "ACCT-REC" and md["table"] == "ACCOUNT"
    by_col = {f["column"]: f for f in md["fields"]}
    assert by_col["ACCT_ID"]["host_var"] == "ACCT-ID"
    assert by_col["ACCT_ID"]["sql_type"] == "INTEGER"
    assert by_col["ACCT_ID"]["category"] == "BINARY"
    assert by_col["ACCT_ID"]["nullable"] is False
    assert by_col["ACCT_BAL"]["nullable"] is True
    assert by_col["ACCT_BAL"]["category"] == "COMP3"
    assert by_col["ACCT_BAL"]["total_digits"] == 7
    assert by_col["ACCT_BAL"]["decimal_digits"] == 2
    assert by_col["ACCT_NAME"]["category"] == "ALPHANUMERIC"
    assert by_col["ACCT_NAME"]["length"] == 20


def test_prefix_applied_to_host_vars() -> None:
    rec = generate(_seed(), "ACCOUNT", record_name="ACCT-REC", prefix="WS-")
    hv = {f["column"]: f["host_var"] for f in rec.metadata["fields"]}
    assert hv["ACCT_ID"] == "WS-ACCT-ID"


# ── VARCHAR 49-group ──────────────────────────────────────────────────────────


def _seed_varchar() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMP (EMP_ID SMALLINT NOT NULL, EMP_NAME VARCHAR(9))")
    return conn


def test_generate_varchar_group_copybook() -> None:
    rec = generate(_seed_varchar(), "EMP", record_name="EMP-REC")
    cpy = rec.copybook
    # The VARCHAR column renders as a 05 group with two 49-level children.
    assert "05  EMP-NAME." in cpy
    assert "49  EMP-NAME-LEN" in cpy and "PIC S9(4) COMP." in cpy
    assert "49  EMP-NAME-TEXT" in cpy and "PIC X(9)." in cpy
    # The 49 children are indented deeper than the 05 group (Area B + nesting).
    group_col = next(ln.index("05") for ln in cpy.splitlines() if "05  EMP-NAME." in ln)
    child_col = next(
        ln.index("49") for ln in cpy.splitlines() if "49  EMP-NAME-LEN" in ln
    )
    assert child_col > group_col


def test_generate_varchar_metadata() -> None:
    rec = generate(_seed_varchar(), "EMP", record_name="EMP-REC")
    by_col = {f["column"]: f for f in rec.metadata["fields"]}
    nm = by_col["EMP_NAME"]
    assert nm["category"] == "VARCHAR"
    assert nm["sql_type"] == "VARCHAR(9)"
    assert nm["length"] == 9
    assert nm["host_var"] == "EMP-NAME"
    # The 49-group children, named so binding can resolve LEN/TEXT from the
    # flat data_layout (which cannot express the group structure).
    assert nm["len_var"] == "EMP-NAME-LEN"
    assert nm["text_var"] == "EMP-NAME-TEXT"
    assert nm["nullable"] is True
