"""The SQL coprocessor's compile spec registers nothing; its runtime installs the builtins."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from interpreter.func_name import FuncName
from interpreter.project.coprocessor_compile import compile_program
from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.vm.builtins import Builtins
from squall.backends.sqlite import SqliteBackend
from squall.coprocessor import build_sql_spec
from squall.runtime import install_sql_runtime
from squall.strategy_stores import register

_HELPERS_PATH = Path(__file__).parent.parent / "integration" / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS_PATH)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

_NAMES = frozenset(
    FuncName(name)
    for name in (
        "__exec_sql",
        "__cics_task_end_hook",
        "__cics_syncpoint_hook",
        "__cics_rollback_hook",
    )
)

_SELECT_INTO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLRUNTM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC 9(4) VALUE 11.
       01 WS-BAL PIC 9(9).
       01 SQLCODE PIC S9(9).
       PROCEDURE DIVISION.
           EXEC SQL CONNECT TO SAMPLE END-EXEC
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           STOP RUN.
"""


def _stand_in(_args: object, vm: object) -> None:
    pass


def test_compile_spec_registers_nothing():
    before = dict(Builtins.TABLE)

    build_sql_spec(tolerant=False).make_strategy()

    assert dict(Builtins.TABLE) == before


def test_install_registers_the_four_builtins():
    [register(str(name), _stand_in) for name in _NAMES]

    install_sql_runtime({"DB": SqliteBackend(sqlite3.connect(":memory:"))})

    assert {n for n in Builtins.TABLE if n in _NAMES} == _NAMES
    assert {n for n in _NAMES if Builtins.TABLE[n] is not _stand_in} == _NAMES


def test_compiled_elsewhere_runs_after_install(tmp_path):
    parser = _helpers.make_cobol_parser(os.environ["PROLEAP_BRIDGE_JAR"])
    linked = compile_program(_SELECT_INTO.encode("utf-8"), parser, [build_sql_spec()])
    linked_file = tmp_path / "program.linked.json"
    LinkedCodec(IrCodec()).write(linked, linked_file)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("installed_runtime_runner.py")),
            str(linked_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "500 0"
