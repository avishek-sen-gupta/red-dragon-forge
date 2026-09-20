"""The composed CardDemo Db2 region -- task 10 of the
2026-09-19-carddemo-db2-tier plan.

``red_dragon_forge`` is the only package the import-linter contracts allow
to import both ``cics`` and ``squall`` (``cics`` must never import
``squall``), so this module is the one place the two runtimes actually meet:
it opens the Db2 connection, builds squall's SQL coprocessor spec over it,
supplies squall's own rollback as cicada's dispatcher-level ``on_abend``
callable (Task 6's seam), and composes both specs via
``cics.tn3270.region.build_region``'s ``extra_specs``.
"""

from __future__ import annotations

from pathlib import Path

import ibm_db
from cics.tn3270.config import RegionConfig
from cics.tn3270.region import ServedRegion, build_region
from squall.backends.db2 import Db2Backend
from squall.connector import NamedDbConnector
from squall.coprocessor import build_sql_spec


def build_db2_region(
    config: RegionConfig, bridge_jar: str, work_dir: Path, dsn: str
) -> tuple[ServedRegion, ibm_db.IBM_DBConnection]:
    """Open *dsn*, build the SQL spec over it, and compose the region.

    ``NamedDbConnector("CARDDEMO")`` models the CICS Db2 attachment
    facility: CARDDEMO is already the current connection when a task
    starts, so COTRTUPC/COTRTLIC's own EXEC SQL statements never need an
    explicit CONNECT. ``tolerant=True`` matches Task 4's verified recipe --
    CardDemo's hand-written DCLGEN copybooks have no JSON sidecars.

    ``backend.rollback`` becomes the dispatcher's ``on_abend`` callable:
    an abending task (unhandled condition, unsupported verb, or a
    dispatcher-level abend such as PGMI/TRNI/AZCT/ASTL) rolls back the open
    Db2 unit of work exactly as EXEC CICS SYNCPOINT ROLLBACK would -- cicada
    never names squall; this module supplies the concrete callable at the
    one seam allowed to know about both.

    Returns the open connection so the caller can close it -- this function
    does not own its lifetime beyond opening it.
    """
    # ibm_db's stub types connect()'s return as IBM_DBConnection | None even
    # though it raises on failure rather than returning None (see
    # squall.backends.db2's own docstring on this exact stub boundary).
    conn = ibm_db.connect(dsn, "", "")  # type: ignore[reportArgumentType]
    backend = Db2Backend(conn)
    sql_spec = build_sql_spec(
        connections={"CARDDEMO": backend},
        copybook_dirs=config.copybook_dirs,
        initial_connector=NamedDbConnector("CARDDEMO"),
        tolerant=True,
    )
    region = build_region(
        config,
        bridge_jar,
        work_dir,
        extra_specs=(sql_spec,),
        on_abend=backend.rollback,
    )
    return region, conn  # type: ignore[reportReturnType]
