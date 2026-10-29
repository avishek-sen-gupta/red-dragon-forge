"""Plain mode runs HLASM binary, hexadecimal and decimal floating point to real values, not symbolic ones."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_FIXTURES = Path(__file__).parent / "fixtures" / "hlasm_fp"
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)


def test_hlasm_floating_point_sums_come_back_to_a_cobol_caller(
    tmp_path: Path,
) -> None:
    build = tmp_path / "build.toml"
    build.write_text(
        f'[cobol]\nsource_dirs = ["{_FIXTURES}"]\nprograms = ["FPDRV"]\n'
        f'[hlasm]\nsource_dirs = ["{_FIXTURES}"]\nprograms = ["ASMFP"]\n'
        '[build]\nname = "fp"\nlink = ["FPDRV", "ASMFP"]\nout_dir = "out"\n'
    )
    assert forge_build([str(build)], os.environ) == 0
    env = tmp_path / "env.toml"
    env.write_text(
        f'package = "{tmp_path / "out" / "fp.zip"}"\n'
        f'[paths]\nsystem = "{tmp_path / "system"}"\n[plain]\nprogram = "FPDRV"\n'
    )

    ran = subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (ran.returncode, ran.stdout.splitlines(), ran.stderr) == (
        0,
        ["BFP 000000375", "HFP 000000375", "DFP 000000375", "RC 0"],
        "",
    )
