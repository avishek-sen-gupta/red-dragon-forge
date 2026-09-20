"""Create and seed CardDemo's Db2 schema. Separate from serving, on purpose.

Preparing a database and running a server are different jobs with different
blast radii, so they are different commands: this one is the only thing that
ever issues ``DROP TABLE``, and ``carddemo-db2-cli`` only ever reads. Folding
the reset into the server's startup would mean every routine start carried the
power to destroy the tables, which is exactly the authority a server does not
need.

    . ./carddemo-env.sh
    . tests/integration/db2_env.sh
    uv run carddemo-db2-seed          # or: make db2-seed

Drops CARDDEMO.TRANSACTION_TYPE(_CATEGORY), recreates them from the vendored
DDL, inserts the seed rows, and commits -- by calling the same
``carddemo_db2_schema.apply_schema`` the integration fixture calls, so the green
screen can never show data the tests never exercised.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import ibm_db

from red_dragon_forge.carddemo_db2_schema import apply_schema

logger = logging.getLogger(__name__)

_DOWN = 1
_UNSET = 2

_CARDDEMO_HOME = "CARDDEMO_HOME"
_DB2_TREE = "app-transaction-type-db2"


def _db2_tree() -> Path:
    """The Db2 source tree holding the DDL, derived as conftest.py derives it."""
    home = os.environ.get(_CARDDEMO_HOME)
    if home:
        return Path(home) / _DB2_TREE
    return Path(__file__).parents[1] / "vendor" / "carddemo" / "app" / _DB2_TREE


def _connect(dsn: str):
    """Open *dsn* with autocommit ON, or exit 1 naming the remedy.

    Autocommit ON and separate from the region's own connection, which
    build_db2_region always flips to SQL_AUTOCOMMIT_OFF -- the same split
    tests/integration/conftest.py makes between db2_admin_conn and the
    program-under-test's connection.
    """
    try:
        conn = ibm_db.connect(dsn, "", "")
    except Exception as exc:
        # ibm_db raises a bare Exception (no narrower public class -- see
        # carddemo_db2_schema._run_tolerating's docstring on this boundary).
        logger.error("Db2 DOWN -- %s", str(exc).split("SQLSTATE")[0].strip()[:100])
        logger.error("If that is SQL30081N, run `make db2-restart`.")
        raise SystemExit(_DOWN) from exc
    ibm_db.autocommit(conn, ibm_db.SQL_AUTOCOMMIT_ON)  # type: ignore[reportArgumentType]
    return conn


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dsn = os.environ.get("SQUALL_DB2_DSN")
    if not dsn:
        logger.error("SQUALL_DB2_DSN unset -- source tests/integration/db2_env.sh")
        return _UNSET
    conn = _connect(dsn)
    logger.info("dropping and reseeding CARDDEMO.TRANSACTION_TYPE(_CATEGORY)")
    apply_schema(conn, _db2_tree())
    ibm_db.close(conn)  # type: ignore[reportArgumentType]
    logger.info(
        "seeded -- start the server with `uv run carddemo-db2-cli --config ...`"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
