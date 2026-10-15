"""A program compiled with the SQL compile spec runs in a fresh process once that process installs the SQL runtime."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from interpreter.project.coprocessor_compile import compile_program
from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from squall.coprocessor import build_sql_spec

_HELPERS_PATH = Path(__file__).with_name("squall_cobol_helpers.py")
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS_PATH)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

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


def test_compiled_elsewhere_runs_after_install(bridge_jar, tmp_path):
    parser = _helpers.make_cobol_parser(bridge_jar)
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
