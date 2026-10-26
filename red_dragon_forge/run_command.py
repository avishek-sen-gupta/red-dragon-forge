"""forge-run: runs a litter package as env.toml says, importing only the runtime its mode needs."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from interpreter.handlers.calls import UnresolvedProgramError
from litter.package_error import PackageError

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_config import run_mode
from red_dragon_forge.run_mode import RunMode


def _cics(path: Path, environ: Mapping[str, str]) -> int:
    from red_dragon_forge.cics_command import run_cics_mode

    return run_cics_mode(path, environ)


def _plain(path: Path, environ: Mapping[str, str]) -> int:
    from red_dragon_forge.plain_command import run_plain_mode

    return run_plain_mode(path, environ)


def _jcl(path: Path, environ: Mapping[str, str]) -> int:
    from red_dragon_forge.jcl_command import run_jcl_mode

    return run_jcl_mode(path, environ)


_COMMAND_OF: Mapping[RunMode, Callable[[Path, Mapping[str, str]], int]] = {
    RunMode.PLAIN: _plain,
    RunMode.JCL: _jcl,
    RunMode.CICS: _cics,
}


def _run(path: Path, environ: Mapping[str, str]) -> int:
    return _COMMAND_OF[run_mode(path)](path, environ)


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
