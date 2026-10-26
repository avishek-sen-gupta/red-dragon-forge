"""forge-run's [cics] mode: the package's CICS region, assembled and served over TN3270."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import partial
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cics.tn3270.region import ServedRegion, assemble_region
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever
from cics.vsam.file_table import FileTableError
from litter.package import Package

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.run_preparation import prepared

logger = logging.getLogger(__name__)


def _region(
    base: Path, config: EnvConfig, package: Package, coprocessing: Coprocessing
) -> ServedRegion:
    return assemble_region(
        package,
        SystemCatalog(base / config.paths.system),
        on_abend=coprocessing.on_abend,
        permit_unresolved_call_targets=config.tolerant.permit_unresolved_call_targets,
        hooks=coprocessing.hooks,
        other_builtins=coprocessing.builtins,
        clock=config.cics.clock(),
    )


def cics_region(path: Path, environ: Mapping[str, str]) -> ServedRegion:
    config, _, package, coprocessing = prepared(path, environ)
    return _region(path.parent, config, package, coprocessing)


def _assembled(
    base: Path, config: EnvConfig, package: Package, coprocessing: Coprocessing
) -> ServedRegion:
    try:
        return _region(base, config, package, coprocessing)
    except FileTableError as exc:
        raise ConfigError(str(exc)) from exc


def run_cics_mode(
    base: Path,
    config: EnvConfig,
    cics: CicsRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    served = _assembled(base, config, package, coprocessing)
    server = bind(cics.host, cics.port)
    logger.info("serving on %s:%d", cics.host, cics.port)
    serve_forever(
        server,
        partial(
            run_session,
            driver=served.driver,
            catalog=served.catalog,
            initial_transid=cics.initial_transid,
        ),
    )
    return 0
