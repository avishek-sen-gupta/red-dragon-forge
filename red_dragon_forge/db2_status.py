"""Report whether Db2 actually answers queries, not merely whether it exists.

``docker ps`` reports the squall-db2 container healthy while the instance inside
it is dead, so every Db2-backed test then fails with SQL30081N and nothing looks
wrong (forge-zka). Only a real connect-and-query distinguishes the two, which is
what this does. The remedy for a dead instance is ``make db2-restart``, NOT
``make db2-up`` -- the container is already up, so ``up`` is a no-op.

Also reports the seeded row count, which says whether ``make db2-seed`` has run.
An absent schema is a state to
report, not an error: Db2 up with nothing seeded is what a first run looks like.

Exit codes are distinct so this can gate a script: 0 up, 1 down, 2 DSN unset.
"""

from __future__ import annotations

import logging
import os

import ibm_db

logger = logging.getLogger(__name__)

_SCHEMA = "CARDDEMO"
_TABLE = "TRANSACTION_TYPE"
_QUALIFIED = f"{_SCHEMA}.{_TABLE}"

_DOWN = 1
_UNSET = 2


def _connect(dsn: str):
    """Open *dsn*, or exit 1 naming the remedy.

    ibm_db raises a bare Exception on failure (no narrower public class -- see
    carddemo_db2_schema._run_tolerating's docstring on this same boundary), so
    catching Exception is the only option; it is re-raised as SystemExit.
    """
    try:
        return ibm_db.connect(dsn, "", "")
    except Exception as exc:
        logger.error("Db2 DOWN -- %s", str(exc).split("SQLSTATE")[0].strip()[:100])
        logger.error("If that is SQL30081N, the container is up but the instance")
        logger.error("is not: run `make db2-restart` -- `make db2-up` is a no-op.")
        raise SystemExit(_DOWN) from exc


def _scalar(conn, sql: str) -> int:
    stmt = ibm_db.exec_immediate(conn, sql)
    row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    # ibm_db's stub types fetch_tuple()'s row as tuple[object, ...]; the driver
    # returns a real int for an integer column.
    return int(next(iter(row)))  # type: ignore[reportArgumentType]


def _report_schema(conn) -> None:
    """Log the seeded row count, or say the schema is absent.

    Asks the catalog whether the table exists rather than counting and catching
    the failure -- the absent case is expected, and an expected case should not
    be routed through an exception handler.
    """
    exists = _scalar(
        conn,
        "SELECT COUNT(*) FROM SYSCAT.TABLES "
        f"WHERE TABSCHEMA = '{_SCHEMA}' AND TABNAME = '{_TABLE}'",
    )
    if not exists:
        logger.info("Db2 UP -- %s absent; run make db2-seed", _QUALIFIED)
        return
    logger.info(
        "Db2 UP -- %s has %d rows",
        _QUALIFIED,
        _scalar(conn, f"SELECT COUNT(*) FROM {_QUALIFIED}"),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dsn = os.environ.get("SQUALL_DB2_DSN")
    if not dsn:
        logger.error("SQUALL_DB2_DSN unset -- source tests/integration/db2_env.sh")
        return _UNSET
    conn = _connect(dsn)
    _report_schema(conn)
    ibm_db.close(conn)  # type: ignore[reportArgumentType]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
