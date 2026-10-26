"""forge-run: runs a litter package as env.toml says, importing only the runtime its mode needs."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from interpreter.handlers.calls import UnresolvedProgramError
from litter.package import Package
from litter.package_error import PackageError

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.env_config import EnvConfig
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.plain_run import PlainRun
from red_dragon_forge.run_preparation import prepared


def _cics(
    base: Path,
    config: EnvConfig,
    cics: CicsRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    from red_dragon_forge.cics_command import run_cics_mode

    return run_cics_mode(base, config, cics, package, coprocessing)


def _plain(
    base: Path,
    config: EnvConfig,
    plain: PlainRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    from red_dragon_forge.plain_command import run_plain_mode

    return run_plain_mode(base, config, plain, package, coprocessing)


def _jcl(
    base: Path,
    config: EnvConfig,
    jcl: JclRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    from red_dragon_forge.jcl_command import run_jcl_mode

    return run_jcl_mode(base, config, jcl, package, coprocessing)


def _run(path: Path, environ: Mapping[str, str]) -> int:
    config, mode, package, coprocessing = prepared(path, environ)
    base = path.parent
    match mode:
        case CicsRun():
            return _cics(base, config, mode, package, coprocessing)
        case _:
            return _batch(base, config, mode, package, coprocessing)


def _batch(
    base: Path,
    config: EnvConfig,
    mode: PlainRun | JclRun,
    package: Package,
    coprocessing: Coprocessing,
) -> int:
    match mode:
        case PlainRun():
            return _plain(base, config, mode, package, coprocessing)
        case JclRun():
            return _jcl(base, config, mode, package, coprocessing)


def run(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    try:
        return _run(Path(argv[0]), environ)
    except (ConfigError, PackageError, UnresolvedProgramError) as unrunnable:
        sys.stderr.write(f"forge-run: {unrunnable}\n")
        return 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    return run(sys.argv[1:], os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
