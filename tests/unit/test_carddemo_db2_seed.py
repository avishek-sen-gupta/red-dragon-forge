"""Unit tests for carddemo_db2_seed: that it reuses the shared apply_schema
rather than restating any DDL or seed rows, and that a missing DSN is a clear
exit rather than a KeyError. The schema logic itself is covered by
tests/integration/test_carddemo_db2_schema.py against a live Db2."""

from __future__ import annotations

import pytest

from red_dragon_forge import carddemo_db2_seed as seed_mod


class _FakeConn:
    pass


def test_seed_calls_the_shared_apply_schema(monkeypatch):
    conn = _FakeConn()
    calls: list[tuple] = []
    monkeypatch.setattr(seed_mod.ibm_db, "connect", lambda *a: conn)
    monkeypatch.setattr(seed_mod.ibm_db, "autocommit", lambda *a: None)
    monkeypatch.setattr(seed_mod.ibm_db, "close", lambda c: None)
    monkeypatch.setattr(
        seed_mod, "apply_schema", lambda c, tree: calls.append((c, tree))
    )
    monkeypatch.setenv("SQUALL_DB2_DSN", "dsn")

    assert seed_mod.main() == 0
    assert len(calls) == 1
    assert calls[0][0] is conn
    assert calls[0][1].name == "app-transaction-type-db2"


def test_missing_dsn_exits_two_without_connecting(monkeypatch):
    def _never(*a):
        raise AssertionError("must not connect without a DSN")

    monkeypatch.setattr(seed_mod.ibm_db, "connect", _never)
    monkeypatch.delenv("SQUALL_DB2_DSN", raising=False)

    assert seed_mod.main() == seed_mod._UNSET


def test_a_dead_db2_exits_one_naming_the_remedy(monkeypatch, caplog):
    def _down(*a):
        raise Exception("SQL30081N communication error SQLSTATE=08001")

    monkeypatch.setattr(seed_mod.ibm_db, "connect", _down)
    monkeypatch.setenv("SQUALL_DB2_DSN", "dsn")

    with pytest.raises(SystemExit) as exc:
        seed_mod.main()
    assert exc.value.code == seed_mod._DOWN
    assert "db2-restart" in caplog.text
