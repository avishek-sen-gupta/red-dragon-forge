"""The composed CardDemo Db2 region -- task 10 of the
2026-09-19-carddemo-db2-tier plan.

``red_dragon_forge`` is the only package the import-linter contracts allow
to import both ``cics`` and ``squall`` (``cics`` must never import
``squall``), so this module is the one place the two runtimes actually meet:
it opens the Db2 connection, installs squall's SQL runtime over it, builds
squall's SQL coprocessor spec, supplies squall's own rollback as cicada's
dispatcher-level ``on_abend`` callable (Task 6's seam), and composes both
specs via
``cics.tn3270.region.compile_region_package``'s ``extra_specs`` before it assembles the
region from the package.
"""

from __future__ import annotations

from pathlib import Path

import ibm_db
from catnip.system_catalog import SystemCatalog
from cics.tn3270.config import RegionConfig
from cics.tn3270.region import ServedRegion, assemble_region, compile_region_package
from litter.open import open_package
from litter.package import Package
from squall.backend import SqlBackend
from squall.backends.db2 import Db2Backend
from squall.connector import NamedDbConnector
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime

from red_dragon_forge.coprocessors import require_linked


def build_db2_region(
    config: RegionConfig, bridge_jar: str, work_dir: Path, dsn: str
) -> tuple[ServedRegion, ibm_db.IBM_DBConnection]:
    """Open *dsn*, install the SQL runtime over it, and compose the region.

    ``NamedDbConnector("CARDDEMO")`` models the CICS Db2 attachment
    facility: CARDDEMO is already the current connection when a task
    starts, so COTRTUPC/COTRTLIC's own EXEC SQL statements never need an
    explicit CONNECT. ``tolerant=True`` matches Task 4's verified recipe:
    host variables missing from the data layout are skipped, not raised.

    ``backend.rollback`` becomes the dispatcher's ``on_abend`` callable:
    an abending task (unhandled condition, unsupported verb, or a
    dispatcher-level abend such as PGMI/TRNI/AZCT/ASTL) rolls back the open
    Db2 unit of work exactly as EXEC CICS SYNCPOINT ROLLBACK would -- cicada
    never names squall; this module supplies the concrete callable at the
    one seam allowed to know about both.

    Returns the open connection so the caller can close it -- this function
    does not own its lifetime beyond opening it.
    """
    require_linked(("sql",), config.programs, "[region] programs")
    # ibm_db's stub types connect()'s return as IBM_DBConnection | None even
    # though it raises on failure rather than returning None (see
    # squall.backends.db2's own docstring on this exact stub boundary).
    conn = ibm_db.connect(dsn, "", "")  # type: ignore[reportArgumentType]
    package = compile_region_package(
        config, bridge_jar, work_dir, work_dir / "out", extra_specs=(build_sql_spec(),)
    )
    region = assembled_db2_region(
        open_package(package), SystemCatalog(config.system), Db2Backend(conn)
    )
    return region, conn  # type: ignore[reportReturnType]


def assembled_db2_region(
    package: Package, system: SystemCatalog, backend: SqlBackend
) -> ServedRegion:
    install_sql_runtime(
        connections={"CARDDEMO": backend},
        initial_connector=NamedDbConnector("CARDDEMO"),
        tolerant=True,
    )
    return assemble_region(package, system, on_abend=backend.rollback)
