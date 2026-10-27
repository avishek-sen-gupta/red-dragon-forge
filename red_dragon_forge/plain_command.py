"""forge-run's [plain] mode: one program run on the package image, with no jackal and no cics."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from interpreter.hlasm_run_inputs.run_input_builtins import (
    unsupplied_run_input_builtins,
)
from interpreter.vm.builtins import compose_builtins, core_builtins
from litter.manifest import Manifest

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_config import EnvConfig
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


def run_plain_mode(path: Path, environ: Mapping[str, str]) -> int:
    config, package, coprocessing = prepared(path, environ, PlainEnv)
    return run_plain(
        package,
        SystemCatalog(path.parent / config.paths.system),
        config.plain,
        compose_builtins(
            core_builtins(), unsupplied_run_input_builtins(), coprocessing.builtins
        ),
        config.tolerant.permit_unresolved_call_targets,
    )
