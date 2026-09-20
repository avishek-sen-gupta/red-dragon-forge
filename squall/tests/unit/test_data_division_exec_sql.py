"""
tests/unit/test_data_division_exec_sql.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for squall.data_division_exec_sql.derive_cursors — recovering
DECLARE CURSOR plans from the raw ProLeap bridge JSON's
"data_division_exec_sql" key (forge-qhi).
"""

from __future__ import annotations

from squall.data_division_exec_sql import derive_cursors


def test_derives_a_declare_cursor_from_working_storage():
    data = {
        "data_division_exec_sql": [
            {
                "section": "WORKING-STORAGE",
                "exec_sql_text": (
                    "EXEC SQL DECLARE C-TR-TYPE-FORWARD CURSOR FOR "
                    "SELECT TR_TYPE FROM CARDDEMO.TRANSACTION_TYPE END-EXEC"
                ),
                "line_start": 571,
            }
        ]
    }

    cursors = derive_cursors(data)

    assert "C-TR-TYPE-FORWARD" in cursors
    assert "TRANSACTION_TYPE" in cursors["C-TR-TYPE-FORWARD"].query


def test_multiple_declares_are_all_recovered():
    data = {
        "data_division_exec_sql": [
            {
                "section": "WORKING-STORAGE",
                "exec_sql_text": (
                    "EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T END-EXEC"
                ),
            },
            {
                "section": "WORKING-STORAGE",
                "exec_sql_text": (
                    "EXEC SQL DECLARE C2 CURSOR FOR SELECT Y FROM T END-EXEC"
                ),
            },
        ]
    }

    cursors = derive_cursors(data)

    assert set(cursors) == {"C1", "C2"}


def test_a_declare_table_is_not_mistaken_for_a_cursor():
    """DECLARE TABLE is precompiler documentation, not a cursor -- it must
    parse without error and simply not appear in the result."""
    data = {
        "data_division_exec_sql": [
            {
                "section": "WORKING-STORAGE",
                "exec_sql_text": (
                    "EXEC SQL DECLARE CARDDEMO.TRANSACTION_TYPE TABLE "
                    "(TR_TYPE CHAR(2) NOT NULL) END-EXEC"
                ),
            }
        ]
    }

    cursors = derive_cursors(data)

    assert cursors == {}


def test_no_data_division_exec_sql_key_yields_no_cursors():
    assert derive_cursors({}) == {}


def test_empty_data_division_exec_sql_yields_no_cursors():
    assert derive_cursors({"data_division_exec_sql": []}) == {}
