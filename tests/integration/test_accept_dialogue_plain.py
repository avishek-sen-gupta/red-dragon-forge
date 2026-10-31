"""A program driving a plain run over pipes sees each prompt before the ACCEPT that waits for its answer, and the answer picks the branch."""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_PROGRAM = Path(__file__).parent / "fixtures" / "ask"
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)
_PATIENCE_SECS = 60


def _env_toml(tmp_path: Path) -> Path:
    build = tmp_path / "build.toml"
    build.write_text(
        "[cobol]\n"
        f'source_dirs = ["{_PROGRAM}"]\n'
        'programs = ["ASK"]\n'
        "[build]\n"
        'name = "ask"\n'
        'link = ["ASK"]\n'
        'out_dir = "out"\n'
    )
    assert forge_build([str(build)], os.environ) == 0
    env = tmp_path / "env.toml"
    env.write_text(
        f'package = "{tmp_path / "out" / "ask.zip"}"\n'
        f'[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "ASK"\n'
    )
    return env


def _read_until(run: subprocess.Popen[bytes], seen: bytes, token: bytes) -> bytes:
    deadline = time.monotonic() + _PATIENCE_SECS
    stdout = run.stdout
    assert stdout is not None
    while token not in seen and time.monotonic() < deadline:
        ready, _, _ = select.select([stdout], [], [], 1)
        seen = seen + (os.read(stdout.fileno(), 4096) if ready else b"")
    return seen


def test_each_prompt_arrives_before_its_answer_is_read(tmp_path: Path) -> None:
    run = subprocess.Popen(
        [sys.executable, "-c", _RUN, str(_env_toml(tmp_path))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdin = run.stdin
    assert stdin is not None

    asked_name = _read_until(run, b"", b"NAME?\n")
    stdin.write(b"BOB\n")
    stdin.flush()
    asked_age = _read_until(run, asked_name, b"AGE?\n")
    stdin.write(b"42\n")
    stdin.close()
    finished = _read_until(run, asked_age, b"RC 0\n")
    run.kill()

    assert (asked_name, asked_age, finished) == (
        b"NAME?\n",
        b"NAME?\nHELLO BOB     \nAGE?\n",
        b"NAME?\nHELLO BOB     \nAGE?\nAGE 42 \nRC 0\n",
    )
