"""CardDemo's COBSWAIT in plain mode: its ACCEPT FROM SYSIN reads the interval from stdin, and MVSWAIT waits that long."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)


def _build_toml(tmp_path: Path, carddemo_home: Path) -> Path:
    path = tmp_path / "build.toml"
    path.write_text(
        "[cobol]\n"
        f'source_dirs = ["{carddemo_home / "cbl"}"]\n'
        'programs = ["COBSWAIT"]\n'
        "[hlasm]\n"
        f'source_dirs = ["{carddemo_home / "asm"}"]\n'
        f'maclib_dirs = ["{carddemo_home / "maclib"}"]\n'
        'programs = ["MVSWAIT"]\n'
        "[build]\n"
        'name = "cobswait"\n'
        'link = ["COBSWAIT", "MVSWAIT"]\n'
        'out_dir = "out"\n'
    )
    return path


def _env_toml(tmp_path: Path, package: Path) -> Path:
    path = tmp_path / "env.toml"
    path.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "COBSWAIT"\n'
    )
    return path


def _timed(env: Path, interval: str) -> tuple[tuple[int, list[str], str], float]:
    started = time.monotonic()
    ran = subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        input=interval,
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        (ran.returncode, ran.stdout.splitlines(), ran.stderr),
        time.monotonic() - started,
    )


def test_cobswait_waits_for_the_interval_read_from_stdin(
    tmp_path: Path, carddemo_home: Path
) -> None:
    assert forge_build([str(_build_toml(tmp_path, carddemo_home))], os.environ) == 0
    env = _env_toml(tmp_path, tmp_path / "out" / "cobswait.zip")

    (no_wait, no_wait_secs), (wait, wait_secs) = (
        _timed(env, "00000000\n"),
        _timed(env, "00000300\n"),
    )

    assert (no_wait, wait, wait_secs - no_wait_secs >= 2.5) == (
        (0, ["RC 0"], ""),
        (0, ["RC 0"], ""),
        True,
    )
