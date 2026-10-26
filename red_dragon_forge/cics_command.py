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
from cics.transaction_hooks import TransactionHooks
from cics.vsam.file_table import FileTableError
from litter.manifest import Manifest
from litter.package import Package
from squall.sql_runtime import SqlRuntime

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.run_preparation import prepared

logger = logging.getLogger(__name__)


class CicsEnv(EnvConfig):
    cics: CicsRun

    def check_loaded(self, path: Path) -> None:
        if "initial_transid" not in self.cics.model_fields_set:
            raise ConfigError(f"{path.name}: [cics] initial_transid is required")

    def check_against(self, path: Path, manifest: Manifest) -> None:
        super().check_against(path, manifest)
        transid = self.cics.initial_transid
        programs = {t.transid: t.program for t in manifest.transactions}
        if transid not in programs:
            raise ConfigError(
                f"{path.name}: transaction {transid} is not in {self.package}"
            )
        if programs[transid] not in manifest.programs:
            raise ConfigError(
                f"{path.name}: transaction {transid} runs {programs[transid]},"
                f" which is not in {self.package}"
            )


def transaction_hooks(sql: SqlRuntime) -> TransactionHooks:
    return TransactionHooks(
        task_end=sql.reset_session, syncpoint=sql.syncpoint, rollback=sql.rollback
    )


def _region(
    base: Path, config: CicsEnv, package: Package, coprocessing: Coprocessing
) -> ServedRegion:
    return assemble_region(
        package,
        SystemCatalog(base / config.paths.system),
        on_abend=coprocessing.on_abend,
        permit_unresolved_call_targets=config.tolerant.permit_unresolved_call_targets,
        hooks=transaction_hooks(coprocessing.sql),
        other_builtins=coprocessing.builtins,
        clock=config.cics.clock(),
    )


def cics_region(path: Path, environ: Mapping[str, str]) -> ServedRegion:
    config, package, coprocessing = prepared(path, environ, CicsEnv)
    return _region(path.parent, config, package, coprocessing)


def _assembled(
    base: Path, config: CicsEnv, package: Package, coprocessing: Coprocessing
) -> ServedRegion:
    try:
        return _region(base, config, package, coprocessing)
    except FileTableError as exc:
        raise ConfigError(str(exc)) from exc


def run_cics_mode(path: Path, environ: Mapping[str, str]) -> int:
    config, package, coprocessing = prepared(path, environ, CicsEnv)
    served = _assembled(path.parent, config, package, coprocessing)
    cics = config.cics
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
