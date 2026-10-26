"""forge-run's [plain] mode: one program run on the package image, with no jackal."""

from __future__ import annotations

from pathlib import Path

from catnip.system_catalog import SystemCatalog
from interpreter.vm.builtins import compose_builtins, core_builtins
from litter.package import Package

from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.plain_mode import run_plain
from red_dragon_forge.plain_run import PlainRun


def run_plain_mode(
    base: Path,
    config: EnvConfig,
    plain: PlainRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    return run_plain(
        package,
        SystemCatalog(base / config.paths.system),
        plain,
        compose_builtins(core_builtins(), coprocessing.builtins),
        config.tolerant.permit_unresolved_call_targets,
    )
