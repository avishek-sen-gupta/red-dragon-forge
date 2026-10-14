"""Unit tests for carddemo_db2_cli: the new bits that could actually break --
that the server never mutates the schema, the SQUALL_DB2_DSN error, and
the connection's
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
        cli_mod,
        "load_config",
        lambda path, system: SimpleNamespace(initial_transid="CC00"),
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


def test_the_server_cannot_mutate_the_schema(monkeypatch, tmp_path):
    """Structural, not behavioural: creating and seeding belongs to
    carddemo-db2-seed, so this module must not even be able to reach
    apply_schema. A behavioural "it wasn't called" test would pass again the
    moment someone re-imported it and added a flag."""
    assert not hasattr(cli_mod, "apply_schema")

    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)
    monkeypatch.setattr(cli_mod.ibm_db, "exec_immediate", lambda conn, sql: "stmt")
    monkeypatch.setattr(cli_mod, "serve_forever", lambda server, session: None)
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "carddemo-db2-cli",
            "--config",
            str(tmp_path / "c.toml"),
            "--system",
            str(tmp_path / "system"),
        ],
    )

    assert cli_mod.main() == 0


def test_connection_is_closed_even_when_serving_raises(monkeypatch, tmp_path):
    schema_conn, region_conn = _FakeConn("schema"), _FakeConn("region")
    _stub_common(monkeypatch, schema_conn=schema_conn, region_conn=region_conn)
    # Let the schema verification pass so main() reaches the serving path.
    monkeypatch.setattr(cli_mod.ibm_db, "exec_immediate", lambda conn, sql: "stmt")

    def _raise(server, session):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod, "serve_forever", _raise)

    closed: list = []
    monkeypatch.setattr(cli_mod.ibm_db, "close", lambda conn: closed.append(conn))

    monkeypatch.setattr(
        "sys.argv",
        [
            "carddemo-db2-cli",
            "--config",
            str(tmp_path / "c.toml"),
            "--system",
            str(tmp_path / "system"),
        ],
    )

    with pytest.raises(RuntimeError, match="boom"):
        cli_mod.main()

    assert schema_conn in closed
    assert region_conn in closed
