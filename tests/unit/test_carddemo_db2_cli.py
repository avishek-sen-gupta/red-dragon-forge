"""Unit tests for carddemo_db2_cli: the new bits that could actually break --
the --reset-schema gate, the SQUALL_DB2_DSN error, and the connection's
lifetime. The wire path itself (bind/serve_forever/run_session) is already
covered by cicada's own suite, so every collaborator here is a stub/spy and
no real server or Db2 connection is ever stood up."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import red_dragon_forge.carddemo_db2_cli as cli_mod


class _FakeConn:
    def __init__(self, name: str):
        self.name = name


def _stub_common(monkeypatch, *, schema_conn, region_conn, served=None):
    """Wires every collaborator except the ones a test wants to observe."""
    monkeypatch.setenv("SQUALL_DB2_DSN", "dsn-string")
    monkeypatch.setenv("PROLEAP_BRIDGE_JAR", "jar.jar")

    connects = iter([schema_conn, region_conn])
    monkeypatch.setattr(cli_mod.ibm_db, "connect", lambda *a, **k: next(connects))
    monkeypatch.setattr(cli_mod.ibm_db, "autocommit", lambda *a, **k: None)

    monkeypatch.setattr(
        cli_mod, "load_config", lambda path: SimpleNamespace(initial_transid="CC00")
    )
    monkeypatch.setattr(
        cli_mod,
        "build_db2_region",
        lambda config, bridge_jar, work_dir, dsn: (
            served or SimpleNamespace(driver="driver", catalog="catalog"),
            region_conn,
        ),
    )
    monkeypatch.setattr(cli_mod, "bind", lambda host, port: "the-server")


def test_reset_schema_flag_calls_apply_schema(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)

    calls: list[tuple] = []
    monkeypatch.setattr(
        cli_mod, "apply_schema", lambda conn, db2_tree: calls.append((conn, db2_tree))
    )
    monkeypatch.setattr(cli_mod, "serve_forever", lambda server, session: None)
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: None)

    monkeypatch.setattr(
        "sys.argv",
        ["carddemo-db2-cli", "--config", str(tmp_path / "c.toml"), "--reset-schema"],
    )

    assert cli_mod.main() == 0
    assert len(calls) == 1
    assert calls[0][0] is schema_conn


def test_without_reset_schema_flag_apply_schema_is_not_called(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)

    def _fail_if_called(conn, db2_tree):
        raise AssertionError("apply_schema must not run without --reset-schema")

    monkeypatch.setattr(cli_mod, "apply_schema", _fail_if_called)
    # The existence check: let it succeed so main() proceeds to serve.
    monkeypatch.setattr(cli_mod.ibm_db, "exec_immediate", lambda conn, sql: "stmt")
    monkeypatch.setattr(cli_mod, "serve_forever", lambda server, session: None)
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: None)

    monkeypatch.setattr(
        "sys.argv", ["carddemo-db2-cli", "--config", str(tmp_path / "c.toml")]
    )

    assert cli_mod.main() == 0


def test_missing_schema_without_reset_fails_loudly(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)

    def _boom(conn, sql):
        raise Exception("SQLSTATE=42704 table not found")

    monkeypatch.setattr(cli_mod.ibm_db, "exec_immediate", _boom)
    monkeypatch.setattr(
        cli_mod, "apply_schema", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: None)

    monkeypatch.setattr(
        "sys.argv", ["carddemo-db2-cli", "--config", str(tmp_path / "c.toml")]
    )

    with pytest.raises(SystemExit, match="re-run with --reset-schema"):
        cli_mod.main()


def test_missing_dsn_fails_with_clear_message_not_keyerror(monkeypatch):
    monkeypatch.delenv("SQUALL_DB2_DSN", raising=False)

    with pytest.raises(SystemExit, match="SQUALL_DB2_DSN"):
        cli_mod._dsn()


def test_connection_is_closed_on_normal_exit(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)

    monkeypatch.setattr(cli_mod, "apply_schema", lambda conn, db2_tree: None)
    monkeypatch.setattr(cli_mod, "serve_forever", lambda server, session: None)

    closed: list = []
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: closed.append(conn))

    monkeypatch.setattr(
        "sys.argv",
        ["carddemo-db2-cli", "--config", str(tmp_path / "c.toml"), "--reset-schema"],
    )

    assert cli_mod.main() == 0
    assert schema_conn in closed
    assert region_conn in closed


def test_connection_is_closed_even_when_serving_raises(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)

    monkeypatch.setattr(cli_mod, "apply_schema", lambda conn, db2_tree: None)

    def _raise(server, session):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod, "serve_forever", _raise)

    closed: list = []
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: closed.append(conn))

    monkeypatch.setattr(
        "sys.argv",
        ["carddemo-db2-cli", "--config", str(tmp_path / "c.toml"), "--reset-schema"],
    )

    with pytest.raises(RuntimeError, match="boom"):
        cli_mod.main()

    assert schema_conn in closed
    assert region_conn in closed
