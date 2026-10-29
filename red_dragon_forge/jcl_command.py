"""forge-run's [jcl] mode: a JCL job run by jackal over the package."""

from __future__ import annotations

import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from interpreter.func_name import FuncName
from interpreter.hlasm_run_inputs.clock_builtins import clock_builtins
from interpreter.hlasm_run_inputs.dd_builtins import NO_DDS, dd_builtins
from interpreter.hlasm_run_inputs.system_machine_clock import SystemMachineClock
from interpreter.vm.builtin import Builtin
from interpreter.vm.builtins import compose_builtins, core_builtins
from jackal.cli import report
from jackal.cobol_step import DEFAULT_PROGRAM_STEP_BUDGET
from jackal.jcl.parser import parse_jcl
from jackal.missing_data import LenientAllocation
from jackal.missing_program import StubMissingProgram
from jackal.model import Job
from jackal.results import JobResult
from jackal.runner import JobRunner
from jackal.unknown_return_code import ZeroUnknownReturnCode
from jackal.unresolved import RaiseErrorStrategy
from litter.package import Package

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.run_preparation import prepared


class JclEnv(EnvConfig):
    jcl: JclRun


def _runner(
    package: Package,
    config: EnvConfig,
    system: Path,
    budget: int,
    proclib_dirs: Sequence[Path],
    coprocessing: Coprocessing,
) -> JobRunner:
    return JobRunner(
        package=package,
        system=SystemCatalog(system),
        unresolved=RaiseErrorStrategy(),
        missing_data=LenientAllocation(),
        missing_program=StubMissingProgram(),
        unknown_return_code=ZeroUnknownReturnCode(),
        program_step_budget=budget,
        proclib_dirs=proclib_dirs,
        builtins=compose_builtins(
            core_builtins(), _run_inputs(), coprocessing.builtins
        ),
        permit_unresolved_call_targets=config.tolerant.permit_unresolved_call_targets,
    )


def _run_inputs() -> Mapping[FuncName, Builtin]:
    clock = SystemMachineClock(
        wall_ns=time.time_ns, cpu_ns=time.process_time_ns, sleep=time.sleep
    )
    return compose_builtins(clock_builtins(clock), dd_builtins(NO_DDS))


def _ran(runner: JobRunner, job: Job) -> JobResult:
    with tempfile.TemporaryDirectory(prefix="forge-run-") as scratch:
        return runner.run(job, Path(scratch))


def _job_text(job: Path) -> str:
    try:
        return job.read_text()
    except OSError as exc:
        raise ConfigError(f"{job}: {exc.strerror}") from exc


def run_jcl_mode(path: Path, environ: Mapping[str, str]) -> int:
    config, package, coprocessing = prepared(path, environ, JclEnv)
    base, jcl = path.parent, config.jcl
    runner = _runner(
        package,
        config,
        base / config.paths.system,
        DEFAULT_PROGRAM_STEP_BUDGET,
        tuple(base / d for d in jcl.proclib_dirs),
        coprocessing,
    )
    return report(_ran(runner, parse_jcl(_job_text(base / jcl.job))))
