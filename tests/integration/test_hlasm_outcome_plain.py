"""Plain mode reports an HLASM entry's return code and abend, and an HLASM callee's abend under a COBOL entry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_FIXTURES = Path(__file__).parent / "fixtures" / "hlasm_outcome"
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)


def built_outcome_package(
    tmp_path: Path, cobol: tuple[str, ...], hlasm: tuple[str, ...]
) -> Path:
    quoted = lambda names: "[" + ", ".join(f'"{n}"' for n in names) + "]"
    build = tmp_path / "build.toml"
    build.write_text(
        f'[cobol]\nsource_dirs = ["{_FIXTURES}"]\nprograms = {quoted(cobol)}\n'
        f'[hlasm]\nsource_dirs = ["{_FIXTURES}"]\nprograms = {quoted(hlasm)}\n'
        f'[build]\nname = "outcome"\nlink = {quoted((*cobol, *hlasm))}\n'
        'out_dir = "out"\n'
    )
    assert forge_build([str(build)], os.environ) == 0
    return tmp_path / "out" / "outcome.zip"


def _forge_run(
    tmp_path: Path, entry: str, cobol: tuple[str, ...], hlasm: tuple[str, ...]
) -> subprocess.CompletedProcess[str]:
    package = built_outcome_package(tmp_path, cobol, hlasm)
    env = tmp_path / "env.toml"
    env.write_text(
        f'package = "{package}"\n'
        f'[paths]\nsystem = "{tmp_path / "system"}"\n[plain]\nprogram = "{entry}"\n'
    )
    return subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )


def _observed(ran: subprocess.CompletedProcess[str]) -> tuple[int, list[str], str]:
    return ran.returncode, ran.stdout.splitlines(), ran.stderr


def test_an_hlasm_main_reports_its_r15_as_the_return_code(tmp_path: Path) -> None:
    assert _observed(_forge_run(tmp_path, "RCEIGHT", (), ("RCEIGHT",))) == (
        0,
        ["RC 8"],
        "",
    )


def test_an_hlasm_main_that_abends_reports_the_abend(tmp_path: Path) -> None:
    assert _observed(_forge_run(tmp_path, "ABEND42", (), ("ABEND42",))) == (
        1,
        ["U0042"],
        "",
    )


def test_an_hlasm_callee_that_abends_under_a_cobol_main_reports_the_abend(
    tmp_path: Path,
) -> None:
    assert _observed(_forge_run(tmp_path, "ABNDDRV", ("ABNDDRV",), ("ASMABND",))) == (
        1,
        ["U0005"],
        "",
    )


def test_an_hlasm_main_that_never_sets_r15_reports_its_entry_address(
    tmp_path: Path,
) -> None:
    assert _observed(_forge_run(tmp_path, "NOSETR15", (), ("NOSETR15",))) == (
        0,
        ["RC 4224"],
        "",
    )
