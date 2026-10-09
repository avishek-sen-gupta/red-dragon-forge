"""
tests/unit/test_grammar_matrix.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Matrix tests covering:
  1. One synthetic statement per directive kind
  2. Hard-case triples: INTO-overload, string colon, SET with CURRENT OF
"""

from __future__ import annotations


import pytest

from squall.parser.parse import parse

# ── Helpers ───────────────────────────────────────────────────────────────────


def _kind(text: str) -> str:
    """Return the directive kind (child rule name) from parsing *text*."""
    tree = parse(text)
    return tree.children[0].data


# ── Synthetic directive matrix ────────────────────────────────────────────────

SYNTHETIC: list[tuple[str, str]] = [
    # (directive_kind, sql_body)
    ("select_into", "SELECT A, B INTO :X, :Y FROM T WHERE ID = :Z"),
    ("insert", "INSERT INTO T (A, B) VALUES (1, 2)"),
    ("update", "UPDATE T SET A = 1 WHERE B = 2"),
    ("delete", "DELETE FROM T WHERE ID = :X"),
    ("merge", "MERGE INTO TARGET T USING SOURCE S ON T.ID = S.ID"),
    ("values_into", "VALUES (:A, :B) INTO :X, :Y"),
    # Cursor DDL / control
    ("declare_cursor", "DECLARE MyCursor CURSOR FOR SELECT A FROM T"),
    ("declare_table", "DECLARE MY_TABLE TABLE (ID INT NOT NULL)"),
    ("declare_statement", "DECLARE STMT1 STATEMENT"),
    ("declare_variable", "DECLARE :HV-VAR VARIABLE CHAR(10)"),
    ("allocate_cursor", "ALLOCATE MY-CUR CURSOR FOR RESULT SET :RS-HV"),
    ("open_", "OPEN MyCursor"),
    ("close", "CLOSE MyCursor"),
    ("fetch", "FETCH FROM MyCursor INTO :A, :B"),
    # Dynamic SQL
    ("prepare", "PREPARE STMT1 FROM :SQL-TEXT"),
    ("execute_", "EXECUTE STMT1 USING :A, :B"),
    ("describe", "DESCRIBE STMT1 INTO :SQLDA-HV"),
    # Transactions
    ("commit", "COMMIT WORK"),
    ("rollback", "ROLLBACK WORK"),
    ("savepoint", "SAVEPOINT MySavepoint"),
    ("release", "RELEASE MySavepoint"),
    # Connections
    ("connect", "CONNECT TO :DB-NAME"),
    ("set_connection", "SET CONNECTION :CONN-NAME"),
    ("disconnect", "DISCONNECT :CONN-NAME"),
    # Error / flow
    ("whenever", "WHENEVER NOT FOUND CONTINUE"),
    ("get_diagnostics", "GET DIAGNOSTICS :COUNT = ROW_COUNT"),
    ("signal", "SIGNAL SQLSTATE '02000'"),
    # Declare-section bookends
    ("begin_declare", "BEGIN DECLARE SECTION"),
    ("end_declare", "END DECLARE SECTION"),
    # Locators
    ("free_locator", "FREE LOCATOR :LOC1, :LOC2"),
    ("hold_locator", "HOLD LOCATOR :LOC1"),
    ("associate", "ASSOCIATE LOCATORS (:LOC) WITH PROCEDURE MY_PROC"),
    # Misc
    ("include", "INCLUDE SQLCA"),
    ("call", "CALL MY_PROC(:A, :B)"),
    ("set", "SET :X = CURRENT DATE"),
    ("lock", "LOCK TABLE T IN SHARE MODE"),
    # Fallback
    ("generic", "GRANT SELECT ON T TO PUBLIC"),
]


@pytest.mark.parametrize("expected_kind,sql", SYNTHETIC, ids=[s[0] for s in SYNTHETIC])
def test_synthetic(expected_kind: str, sql: str) -> None:
    assert _kind(sql) == expected_kind


# ── Hard-case triples ─────────────────────────────────────────────────────────


def _hv_names(tree) -> list[str]:
    """Extract all primary host-var names from a parse tree."""
    names = []
    for hv in tree.find_data("host_var"):
        for tok in hv.children:
            if hasattr(tok, "type") and tok.type == "HOST_VAR_TOK":
                parts = [s for s in tok.value.split(":") if s]
                if parts:
                    names.append(parts[0])
                break
    return names


def test_into_overload() -> None:
    """SELECT … INTO … FROM must not confuse the INTO in the column list."""
    sql = "SELECT A INTO :X FROM T WHERE B = :Y"
    assert _kind(sql) == "select_into"
    tree = parse(sql)
    names = _hv_names(tree)
    assert "X" in names and "Y" in names


def test_string_colon_in_matrix() -> None:
    """String-embedded colons must not be mistaken for host-variable markers."""
    sql = "SELECT A INTO :OUT FROM T WHERE X = 'literal :colon' AND Y = :IN"
    assert _kind(sql) == "select_into"
    tree = parse(sql)
    primary_names = _hv_names(tree)
    assert primary_names == ["OUT", "IN"]


def test_set_current_date_where_current_of() -> None:
    """UPDATE with SET x = CURRENT DATE … WHERE CURRENT OF cursor must parse."""
    sql = "UPDATE T SET X = CURRENT DATE WHERE CURRENT OF MY_CUR"
    assert _kind(sql) == "update"
