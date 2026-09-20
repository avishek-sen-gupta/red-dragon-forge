"""Serve the composed CICS+SQL CardDemo region to 3270 emulators.

. ./carddemo-env.sh
. tests/integration/db2_env.sh
uv run carddemo-db2-cli --config cicada/config/carddemo-db2-tn3270.toml --port 3271 --reset-schema
c3270 -model 3278-2 localhost:3271
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
from red_dragon_forge.carddemo_db2_schema import apply_schema

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
    parser.add_argument(
        "--reset-schema",
        action="store_true",
        help=(
            "Drop and recreate CARDDEMO.TRANSACTION_TYPE(_CATEGORY) from the "
            "vendored DDL and reseed them before serving. Without this flag, "
            "the schema is assumed to already exist and is only checked, "
            "never dropped -- see carddemo_db2_schema's module docstring on "
            "why an implicit reset is never safe to default to."
        ),
    )
    return parser.parse_args(argv)


def _dsn() -> str:
    """The live Db2 DSN, or a clear failure -- never a bare KeyError."""
    dsn = os.environ.get("SQUALL_DB2_DSN")
    if not dsn:
        raise SystemExit(_DSN_HINT)
    return dsn


def _db2_tree() -> Path:
    """Same derivation as tests/integration/conftest.py's ``carddemo_home``
    fixture: CARDDEMO_HOME (exported by carddemo-env.sh) joined with the
    Db2-tree subdirectory, never a new config key."""
    carddemo_home = Path(
        os.environ.get(
            "CARDDEMO_HOME",
            str(Path(__file__).resolve().parents[1] / "vendor" / "carddemo" / "app"),
        )
    )
    return carddemo_home / "app-transaction-type-db2"


def _ensure_schema(conn, db2_tree: Path, reset: bool) -> None:
    """Apply the schema when *reset*, else verify it exists cheaply.

    Applying by default would run ``DROP TABLE`` against whatever Db2 the
    caller points this at -- the VSAM options only ever seed a temp-dir
    *copy*, but this one command destroys a real database's tables. So the
    default path never drops anything; it fails loudly at startup instead of
    letting a missing schema abend the first screen a terminal paints.
    """
    if reset:
        logger.info(
            "--reset-schema: dropping and reseeding "
            "CARDDEMO.TRANSACTION_TYPE(_CATEGORY)"
        )
        apply_schema(conn, db2_tree)
        return
    try:
        ibm_db.exec_immediate(conn, "SELECT COUNT(*) FROM CARDDEMO.TRANSACTION_TYPE")
    except Exception as exc:
        # ibm_db raises a bare Exception on failure (no narrower public
        # class -- see carddemo_db2_schema._run_tolerating's own docstring
        # on this same boundary), so this is the only way to catch it.
        raise SystemExit(
            "CARDDEMO.TRANSACTION_TYPE is missing or unreadable "
            f"({exc}); re-run with --reset-schema to create and seed it."
        ) from exc


def _prepare_schema(dsn: str, db2_tree: Path, reset: bool) -> None:
    """Open a connection dedicated to schema setup/verification, autocommit
    ON -- kept separate from the region's own connection (build_db2_region's
    Db2Backend always flips its connection to SQL_AUTOCOMMIT_OFF), matching
    tests/integration/conftest.py's db2_admin_conn/carddemo_db2_schema split.
    """
    schema_conn = ibm_db.connect(dsn, "", "")
    ibm_db.autocommit(schema_conn, ibm_db.SQL_AUTOCOMMIT_ON)  # type: ignore[reportArgumentType]
    try:
        _ensure_schema(schema_conn, db2_tree, reset)
    finally:
        ibm_db.close(schema_conn)  # type: ignore[reportArgumentType]


def _serve(
    config, bridge_jar: str, work_dir: Path, dsn: str, host: str, port: int
) -> None:
    """Build the composed region and serve it until interrupted, closing its
    Db2 connection on the way out even if serving raises."""
    served, conn = build_db2_region(config, bridge_jar, work_dir, dsn)
    try:
        server = bind(host, port)
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
    db2_tree = _db2_tree()
    _prepare_schema(dsn, db2_tree, args.reset_schema)
    logger.info("serving %s on %s:%d", args.config, args.host, args.port)
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
