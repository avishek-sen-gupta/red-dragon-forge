"""A SQL program lowered in one process runs in another with no lowering state."""

import importlib.util
import pickle
import sqlite3
import subprocess
import sys
from pathlib import Path

from squall.backends.sqlite import SqliteBackend
from squall.dclgen import generate, write


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_helpers = _load("squall_cobol_helpers")
_VARCHAR_PROGRAM = _load("test_crud_e2e")._VARCHAR_PROGRAM


def test_a_program_lowered_here_runs_in_a_fresh_process(bridge_jar, tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMP (EMP_ID INTEGER NOT NULL, EMP_NAME VARCHAR(9))")
    write(generate(conn, "EMP", record_name="EMPREC"), tmp_path)
    linked = _helpers.compile_cobol(
        _VARCHAR_PROGRAM,
        bridge_jar,
        {"SAMPLE": SqliteBackend(conn)},
        copybook_dirs=[tmp_path],
    )
    unit = tmp_path / "unit.pickle"
    unit.write_bytes(pickle.dumps(linked))

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("cross_process_runner.py")),
            str(unit),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "7 SANDERS"
