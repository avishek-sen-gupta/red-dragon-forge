"""Shared fixtures for red-dragon-forge integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import ibm_db
import pytest

from red_dragon_forge.carddemo_db2_schema import apply_schema
from tests.carddemo_packages import DB2, ONLINE, built_package


@pytest.fixture(scope="session")
def carddemo_online_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return built_package(tmp_path_factory.mktemp("carddemo_online"), ONLINE)


@pytest.fixture(scope="session")
def carddemo_db2_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return built_package(tmp_path_factory.mktemp("carddemo_db2"), DB2)


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path — required, no default, no skip."""
    return os.environ["PROLEAP_BRIDGE_JAR"]


@pytest.fixture
def jcl_bridge_jar() -> str:
    """The jcl-bridge JAR path — required, no default, no skip."""
    return os.environ["JCL_BRIDGE_JAR"]


@pytest.fixture
def carddemo_home() -> Path:
    """Root of the CardDemo checkout. Uses the shared vendor/carddemo
    submodule by default (it has cbl/, cpy/, csd/, and jcl/ all present);
    CARDDEMO_HOME overrides."""
    env = os.environ.get("CARDDEMO_HOME")
    if env:
        return Path(env)
    default = Path(__file__).parents[2] / "vendor" / "carddemo" / "app"
    if not default.is_dir():
        pytest.skip(f"CardDemo checkout not found at {default}; set CARDDEMO_HOME")
    return default


@pytest.fixture
def db2_dsn() -> str:
    """The live Db2 DSN — skips (not fail-loud) when unset, since the Db2
    tier's tests are additive to a suite that otherwise runs without any
    database at all; source tests/integration/db2_env.sh to set it."""
    dsn = os.environ.get("SQUALL_DB2_DSN")
    if not dsn:
        pytest.skip("SQUALL_DB2_DSN not set; source tests/integration/db2_env.sh")
    return dsn


@pytest.fixture
def db2_admin_conn(db2_dsn: str):
    """A connection dedicated to DDL and seeding, autocommit ON.

    Kept separate from the program-under-test's own connection (which
    Db2Backend.__init__ always flips to SQL_AUTOCOMMIT_OFF) so schema setup
    is never at the mercy of that program's own unit-of-work boundaries, and
    separate from db2_probe_conn so a test's own committed-state assertions
    never share a session with the setup that produced them."""
    # ibm_db's stub types connect()'s return as IBM_DBConnection | None even
    # though it raises on failure rather than returning None (see
    # squall.backends.db2's own docstring on this same stub boundary).
    conn = ibm_db.connect(db2_dsn, "", "")
    ibm_db.autocommit(conn, ibm_db.SQL_AUTOCOMMIT_ON)  # type: ignore[reportArgumentType]
    # Bounded, not unbounded: this connection's DROP TABLE (carddemo_db2_schema,
    # function-scoped) runs against whatever the module-scoped `region` fixture's
    # own connection is holding. Every test's last turn today ends in EXEC CICS
    # RETURN, which commits and releases locks before the next test's schema
    # setup ever runs -- but that invariant is undocumented and unenforced.
    # A turn that abends, or a `pytest -x` failure mid-test, could leave an S/X
    # lock the region's connection never releases; without a timeout the next
    # DROP TABLE would then wait forever instead of failing loud.
    ibm_db.exec_immediate(conn, "SET CURRENT LOCK TIMEOUT 10")  # type: ignore[reportArgumentType]
    yield conn
    ibm_db.close(conn)  # type: ignore[reportArgumentType]


@pytest.fixture
def db2_probe_conn(db2_dsn: str):
    """A THIRD connection, used only to assert on committed state.

    This is the load-bearing fixture in this file. Asserting through the
    program-under-test's own Db2Backend connection cannot distinguish
    "committed" from "merely still visible on the same session" — every one
    of Task 6's unit-of-work fixes (SYNCPOINT was a no-op, XCTL fired no
    rollback hook, an abend told squall nothing) would leave the program's
    own connection looking correct while nothing had actually reached the
    database. Only a separate connection's read proves the write survived a
    COMMIT (or was undone by a ROLLBACK)."""
    conn = ibm_db.connect(db2_dsn, "", "")
    ibm_db.autocommit(conn, ibm_db.SQL_AUTOCOMMIT_ON)  # type: ignore[reportArgumentType]
    # Pinned explicitly, not left to Db2's ``cur_commit`` default: the
    # commit-boundary proof (test_the_update_is_committed_before_the_task_returns)
    # depends on this probe being unable to see another connection's
    # uncommitted write. READ_UNCOMMITTED would let that test pass even with
    # SYNCPOINT reverted to a no-op, because it would read the row before the
    # writer's own COMMIT. READ_COMMITTED (cursor stability) is the weakest
    # level that still can't do that, so it's pinned here rather than trusted
    # to whatever the DSN or the server's cur_commit setting happens to be.
    # set_option returns False rather than raising, so an unchecked call would
    # leave a wrong constant or option scope silently at the default -- making
    # the pin above unfalsifiable in exactly the way it exists to prevent.
    assert ibm_db.set_option(
        conn,  # type: ignore[reportArgumentType]
        {ibm_db.SQL_ATTR_TXN_ISOLATION: ibm_db.SQL_TXN_READ_COMMITTED},
        1,
    )
    yield conn
    ibm_db.close(conn)  # type: ignore[reportArgumentType]


@pytest.fixture
def carddemo_db2_schema(db2_admin_conn, carddemo_home: Path):
    """Applies the CARDDEMO schema/seed (task 10's Step 1) over
    db2_admin_conn -- autocommit ON there, so every DDL/DML statement is
    committed the instant it runs, well before any test constructs a
    Db2Backend over a *different* connection."""
    db2_tree = carddemo_home / "app-transaction-type-db2"
    apply_schema(db2_admin_conn, db2_tree)
    yield
