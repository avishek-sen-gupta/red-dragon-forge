"""CardDemo's assembler MVSWAIT in plain mode, called with a fixed interval by a driver standing in for COBSWAIT's ACCEPT: its STIMER WAIT really pauses the run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_DRIVER = Path(__file__).parent / "fixtures" / "waitdrv"
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)


def _build_toml(tmp_path: Path, carddemo_home: Path) -> Path:
    path = tmp_path / "build.toml"
    path.write_text(
        "[cobol]\n"
        f'source_dirs = ["{_DRIVER}"]\n'
        'programs = ["WAITDRV"]\n'
        "[hlasm]\n"
        f'source_dirs = ["{carddemo_home / "asm"}"]\n'
        f'maclib_dirs = ["{carddemo_home / "maclib"}"]\n'
        'programs = ["MVSWAIT"]\n'
        "[build]\n"
        'name = "waitdrv"\n'
        'link = ["WAITDRV", "MVSWAIT"]\n'
        'out_dir = "out"\n'
    )
    return path


def _env_toml(tmp_path: Path, package: Path) -> Path:
    path = tmp_path / "env.toml"
    path.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "WAITDRV"\n'
    )
    return path


def test_mvswait_pauses_for_the_interval_its_caller_passes(
    tmp_path: Path, carddemo_home: Path
) -> None:
    assert forge_build([str(_build_toml(tmp_path, carddemo_home))], os.environ) == 0
    env = _env_toml(tmp_path, tmp_path / "out" / "waitdrv.zip")

    ran = subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (ran.returncode, ran.stdout.splitlines(), ran.stderr) == (
        0,
        ["WAITED", "RC 0"],
        "",
    )
