"""forge-run's [plain] mode: one program run on the package image, with no jackal and no cics."""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from interpreter.hlasm_run_inputs.job_parm_builtins import NO_PARM
from interpreter.hlasm_run_inputs.run_input_builtins import run_input_builtins
from interpreter.hlasm_run_inputs.system_machine_clock import SystemMachineClock
from interpreter.vm.builtins import compose_builtins, core_builtins
from litter.manifest import Manifest
from zos.cobol.io.system_input import line_input

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.floating_point_builtins import floating_point_builtins
from red_dragon_forge.plain_mode import run_plain
from red_dragon_forge.plain_run import PlainRun
from red_dragon_forge.run_preparation import prepared


class PlainEnv(EnvConfig):
    plain: PlainRun

    def check_against(self, path: Path, manifest: Manifest) -> None:
        super().check_against(path, manifest)
        if self.plain.program not in manifest.programs:
            raise ConfigError(
                f"{path.name}: program {self.plain.program} is not in {self.package}"
            )


def _prompted_line() -> str:
    sys.stdout.flush()
    return sys.stdin.readline()


def run_plain_mode(path: Path, environ: Mapping[str, str]) -> int:
    config, package, coprocessing = prepared(path, environ, PlainEnv)
    return run_plain(
        package,
        SystemCatalog(path.parent / config.paths.system),
        config.plain,
        compose_builtins(
            core_builtins(),
            run_input_builtins(
                SystemMachineClock(
                    wall_ns=time.time_ns, cpu_ns=time.process_time_ns, sleep=time.sleep
                ),
                NO_PARM,
            ),
            floating_point_builtins(),
            coprocessing.builtins,
        ),
        line_input(iter(_prompted_line, "")),
        config.tolerant.permit_unresolved_call_targets,
    )
