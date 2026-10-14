"""Serve the composed CICS+SQL CardDemo region to 3270 emulators.

. ./carddemo-env.sh
. tests/integration/db2_env.sh
uv run carddemo-db2-seed          # once, to create and seed the schema
uv run catnip install config/carddemo/data.toml --system /tmp/carddemo-system
uv run carddemo-db2-cli --config cicada/config/carddemo-db2-tn3270.toml --port 3271
c3270 -model 3279-2-E localhost:3271   # 3279 + -E, or you get monochrome
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import ibm_db
from cics.tn3270.config import load_config
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever

from red_dragon_forge.carddemo_db2_region import build_db2_region

logger = logging.getLogger(__name__)

_DSN_HINT = (
    "SQUALL_DB2_DSN is not set; source tests/integration/db2_env.sh "
    "(after carddemo-env.sh) to export it."
)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3270)
    return parser.parse_args(argv)


def _dsn() -> str:
    """The live Db2 DSN, or a clear failure -- never a bare KeyError."""
    dsn = os.environ.get("SQUALL_DB2_DSN")
    if not dsn:
        raise SystemExit(_DSN_HINT)
    return dsn


def _verify_schema(conn) -> None:
    """Confirm the schema is there, and never touch it.

    This command only ever READS. Creating and seeding belongs to
    ``carddemo-db2-seed``, because that is the only thing that issues
    ``DROP TABLE`` and a server has no business carrying that authority on
    every routine start. Failing here beats letting a missing schema abend
    the first screen a terminal paints.
    """
    try:
        ibm_db.exec_immediate(conn, "SELECT COUNT(*) FROM CARDDEMO.TRANSACTION_TYPE")
    except Exception as exc:
        # ibm_db raises a bare Exception on failure (no narrower public
        # class -- see carddemo_db2_schema._run_tolerating's own docstring
        # on this same boundary), so this is the only way to catch it.
        raise SystemExit(
            "CARDDEMO.TRANSACTION_TYPE is missing or unreadable "
            f"({exc}); run `make db2-seed` (uv run carddemo-db2-seed) first."
        ) from exc


def _require_schema(dsn: str) -> None:
    """Open a connection dedicated to schema setup/verification, autocommit
    ON -- kept separate from the region's own connection (build_db2_region's
    Db2Backend always flips its connection to SQL_AUTOCOMMIT_OFF), matching
    tests/integration/conftest.py's db2_admin_conn/carddemo_db2_schema split.
    """
    schema_conn = ibm_db.connect(dsn, "", "")
    ibm_db.autocommit(schema_conn, ibm_db.SQL_AUTOCOMMIT_ON)  # type: ignore[reportArgumentType]
    try:
        _verify_schema(schema_conn)
    finally:
        ibm_db.close(schema_conn)  # type: ignore[reportArgumentType]


def _built(config, bridge_jar: str, work_dir: Path, dsn: str):
    """Build the composed region, saying so first: compiling every program in
    the config takes about a minute, and the bridge's own progress bar names no
    program, so silence here reads as a hang."""
    logger.info("compiling the region's programs (about a minute)")
    return build_db2_region(config, bridge_jar, work_dir, dsn)


def _bound(host: str, port: int):
    """Bind, and only THEN say we are serving -- announcing it before the
    region compiles is what made a working start look wedged."""
    server = bind(host, port)
    logger.info("serving on %s:%d -- ready for a 3270 to connect", host, port)
    return server


def _serve(
    config, bridge_jar: str, work_dir: Path, dsn: str, host: str, port: int
) -> None:
    """Build the composed region and serve it until interrupted, closing its
    Db2 connection on the way out even if serving raises."""
    served, conn = _built(config, bridge_jar, work_dir, dsn)
    try:
        server = _bound(host, port)
        session = partial(
            run_session,
            driver=served.driver,
            catalog=served.catalog,
            initial_transid=config.initial_transid,
        )
        serve_forever(server, session)
    finally:
        ibm_db.close(conn)  # type: ignore[reportArgumentType]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _arguments(sys.argv[1:])
    dsn = _dsn()
    config = load_config(args.config)
    _require_schema(dsn)
    with tempfile.TemporaryDirectory(prefix="carddemo-db2-tn3270-") as work_dir:
        _serve(
            config,
            os.environ["PROLEAP_BRIDGE_JAR"],
            Path(work_dir),
            dsn,
            args.host,
            args.port,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
