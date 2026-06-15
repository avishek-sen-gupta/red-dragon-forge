"""
tests/unit/test_connection.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Faithful CONNECT: registry routing + per-run connection lifecycle (squall-yml).
"""

from __future__ import annotations

from squall.parser.parse import HostVar, parse_exec_sql


def test_parse_connect_to_literal():
    p = parse_exec_sql("EXEC SQL CONNECT TO sample END-EXEC")
    assert p.kind == "connect"
    assert p.connect_variant == "TO"
    assert p.connect_db == "SAMPLE"  # DB2 upper-cases database names


def test_parse_connect_to_hostvar():
    p = parse_exec_sql("EXEC SQL CONNECT TO :dbname USER :u USING :p END-EXEC")
    assert p.connect_variant == "TO"
    assert p.connect_db == HostVar(name="dbname", indicator=None)


def test_parse_connect_to_literal_with_creds_ignores_creds():
    # The testbed double-CONNECT idiom: literal db + USER/USING creds. The creds
    # surface in in_vars but the target is the literal, and creds are unread.
    p = parse_exec_sql("EXEC SQL CONNECT TO sample USER :userid USING :passwd END-EXEC")
    assert p.connect_variant == "TO"
    assert p.connect_db == "SAMPLE"


def test_parse_connect_reset():
    p = parse_exec_sql("EXEC SQL CONNECT RESET END-EXEC")
    assert p.connect_variant == "RESET"
    assert p.connect_db is None


def test_parse_set_connection():
    p = parse_exec_sql("EXEC SQL SET CONNECTION db2 END-EXEC")
    assert p.kind == "set_connection"
    assert p.connect_db == "DB2"


def test_parse_disconnect():
    p = parse_exec_sql("EXEC SQL DISCONNECT db2 END-EXEC")
    assert p.kind == "disconnect"
    assert p.connect_db == "DB2"
