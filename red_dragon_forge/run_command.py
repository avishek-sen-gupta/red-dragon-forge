"""forge-run: runs a litter package as env.toml says: one program, a JCL job, or a CICS region over TN3270."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path
from zipfile import BadZipFile

from catnip.system_catalog import SystemCatalog
from cics.tn3270.region import ServedRegion, assemble_region
from cics.tn3270.session import run_session
from cics.tn3270.wire import bind, serve_forever
from cics.vsam.file_table import FileTableError
from interpreter.handlers.calls import UnresolvedProgramError
from jackal.cli import report
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.jcl.wire import disp_from_words
from jackal.missing_data import LenientAllocation
from jackal.missing_program import StubMissingProgram
from jackal.model import DD, DdName, DirectDSN, Job, ProgramRef, ProgramStep, StepName
from jackal.results import Abended, JobResult
from jackal.runner import JobRunner
from jackal.unresolved import RaiseErrorStrategy
from jackal.value_parts import literal
from litter.open import open_package
from litter.package import Package
from litter.package_error import PackageError

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.db2_connection import connected
from red_dragon_forge.env_config import (
    EnvConfig,
    RunMode,
    check_against,
    load_env_config,
)
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.plain_run import PlainRun

logger = logging.getLogger(__name__)

_PLAIN_STEP = "PLAIN"
_DSN = "SQUALL_DB2_DSN"


def _noop() -> None:
    return None


def _runner(
    package: Package,
    config: EnvConfig,
    system: Path,
    budget: int,
    proclib_dirs: Sequence[Path],
) -> JobRunner:
    return JobRunner(
        package=package,
        system=SystemCatalog(system),
        unresolved=RaiseErrorStrategy(),
        missing_data=LenientAllocation(),
        missing_program=StubMissingProgram(),
        program_step_budget=budget,
        proclib_dirs=proclib_dirs,
        permit_unresolved_call_targets=config.tolerant.permit_unresolved_call_targets,
    )


def plain_job(plain: PlainRun) -> Job:
    return Job(
        _PLAIN_STEP,
        (
            ProgramStep(
                StepName(_PLAIN_STEP),
                ProgramRef(plain.program),
                tuple(
                    DD(
                        DdName(assign),
                        DirectDSN(literal(dsn)),
                        disp_from_words(("SHR",)),
                    )
                    for assign, dsn in plain.files.items()
                ),
            ),
        ),
    )


def _ran(runner: JobRunner, job: Job) -> JobResult:
    with tempfile.TemporaryDirectory(prefix="forge-run-") as scratch:
        return runner.run(job, Path(scratch))


def _plain(base: Path, config: EnvConfig, plain: PlainRun, package: Package) -> int:
    runner = _runner(package, config, base / config.paths.system, plain.max_steps, ())
    result = _ran(runner, plain_job(plain))
    sys.stdout.write("".join(f"{s.outcome.rendered()}\n" for s in result.steps))
    return 1 if any(isinstance(s.outcome, Abended) for s in result.steps) else 0


def _jcl(base: Path, config: EnvConfig, jcl: JclRun, package: Package) -> int:
    runner = _runner(
        package,
        config,
        base / config.paths.system,
        DEFAULT_PROGRAM_STEP_BUDGET,
        tuple(base / d for d in jcl.proclib_dirs),
    )
    return report(_ran(runner, parse_jcl(_job_text(base / jcl.job))))


def _job_text(job: Path) -> str:
    try:
        return job.read_text()
    except OSError as exc:
        raise ConfigError(f"{job}: {exc.strerror}") from exc


def _cics(
    base: Path,
    config: EnvConfig,
    cics: CicsRun,
    package: Package,
    on_abend: Callable[[], None],
) -> int:
    served = _region(base, config, package, on_abend)
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


def _rollback(
    config: EnvConfig, package: Package, environ: Mapping[str, str]
) -> Callable[[], None]:
    if "sql" not in package.manifest.coprocessors:
        return _noop
    if not environ.get(_DSN, ""):
        raise ConfigError(f"{_DSN} is not set")
    return connected(environ[_DSN]).install(
        config.tolerant.permit_missing_host_variables
    )


def _package(path: Path, config: EnvConfig) -> Package:
    try:
        return open_package(path.parent / config.package)
    except (OSError, BadZipFile) as exc:
        raise ConfigError(f"{path.name}: package {config.package}: {exc}") from exc


def _region(
    base: Path, config: EnvConfig, package: Package, on_abend: Callable[[], None]
) -> ServedRegion:
    return assemble_region(
        package,
        SystemCatalog(base / config.paths.system),
        on_abend=on_abend,
        permit_unresolved_call_targets=config.tolerant.permit_unresolved_call_targets,
    )


def _prepared(
    path: Path, environ: Mapping[str, str]
) -> tuple[EnvConfig, RunMode, Package, Callable[[], None]]:
    config, mode = load_env_config(path)
    package = _package(path, config)
    check_against(path, config, mode, package.manifest)
    return config, mode, package, _rollback(config, package, environ)


def cics_region(path: Path, environ: Mapping[str, str]) -> ServedRegion:
    config, _, package, on_abend = _prepared(path, environ)
    return _region(path.parent, config, package, on_abend)


def _run(path: Path, environ: Mapping[str, str]) -> int:
    config, mode, package, on_abend = _prepared(path, environ)
    base = path.parent
    match mode:
        case CicsRun():
            return _cics(base, config, mode, package, on_abend)
        case _:
            return _batch(base, config, mode, package)


def _batch(
    base: Path, config: EnvConfig, mode: PlainRun | JclRun, package: Package
) -> int:
    match mode:
        case PlainRun():
            return _plain(base, config, mode, package)
        case JclRun():
            return _jcl(base, config, mode, package)


def run(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    try:
        return _run(Path(argv[0]), environ)
    except (
        ConfigError,
        PackageError,
        FileTableError,
        UnresolvedProgramError,
    ) as unrunnable:
        sys.stderr.write(f"forge-run: {unrunnable}\n")
        return 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    return run(sys.argv[1:], os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
