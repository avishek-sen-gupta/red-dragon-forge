"""Integration (JAR-gated): the CEEDAYS LE-service stub validates dates.

CSUTLDTC.cbl CALLs the IBM Language Environment service CEEDAYS to validate a
date; there is no COBOL source for CEEDAYS, so we supply a stub
(``cics/stubs/CEEDAYS.cbl``). These tests drive a tiny
COBOL caller that mirrors CSUTLDTC's CALL shape (a Vstring date + a feedback
token) and assert the feedback severity: 0 for a valid Gregorian date, nonzero
for an invalid one. The stub is linked like any other CALLed subprogram via the
project linker.
"""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.features import CobolFeature
from cics.le_stubs import LE_STUBS_DIR
from cobol_asg.cobol_parser import make_cobol_parser
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.source_file import SourceFile
from interpreter.run import run_linked, EntryPoint, initial_vm_state
from interpreter.cobol.program_object import WORKING_STORAGE_FIELD, program_var
from interpreter.address import Address
from interpreter.vm.builtins import core_builtins
from tests.covers import covers


# Caller mirrors CSUTLDTC's CALL: a Vstring date (S9(4) BINARY length + 10-char
# text) and a feedback token. After the CALL it copies the severity halfword
# into a plain PIC 9(4) field WS-SEV (exactly as CSUTLDTC does), so the test can
# read back '0000' for valid / nonzero for invalid from the WS region.
def _caller_src(date_text: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DRIVER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SEV          PIC 9(4) VALUE 9999.
       01 WS-DATE-VS.
          05 WS-DATE-LEN   PIC S9(4) BINARY VALUE 10.
          05 WS-DATE-TXT   PIC X(256).
       01 WS-FMT-VS.
          05 WS-FMT-LEN    PIC S9(4) BINARY VALUE 10.
          05 WS-FMT-TXT    PIC X(256).
       01 WS-LILIAN        PIC S9(9) BINARY VALUE 0.
       01 WS-FEEDBACK.
          05 WS-FB-SEV     PIC S9(4) BINARY VALUE 0.
          05 WS-FB-MSG     PIC S9(4) BINARY VALUE 0.
          05 FILLER        PIC X(8).
       PROCEDURE DIVISION.
           MOVE '{date_text}' TO WS-DATE-TXT.
           MOVE 'YYYY-MM-DD' TO WS-FMT-TXT.
           CALL 'CEEDAYS' USING WS-DATE-VS WS-FMT-VS
                                WS-LILIAN WS-FEEDBACK.
           MOVE WS-FB-SEV TO WS-SEV.
           STOP RUN.
"""


def _run_and_read_sev(tmp_path: Path, date_text: str) -> int:
    """Compile DRIVER + the CEEDAYS stub, run, and return WS-SEV (the severity)."""
    stub = LE_STUBS_DIR / "CEEDAYS.cbl"
    linked = compile_cobol(
        _caller_src(date_text).encode(),
        parser=make_cobol_parser(),
        programs=(SourceFile(stub, stub.read_bytes()),),
    )
    vm = run_linked(
        linked,
        EntryPoint.function(lambda r: r.label == linked.entry_func_label),
        max_steps=200_000,
        initial_vm=initial_vm_state(),
        builtins=core_builtins(),
    )

    # Read WS-SEV (offset 0, 4 zoned-decimal bytes) from DRIVER's WS region.
    for frame in reversed(vm.call_stack):
        if program_var("DRIVER") in frame.local_vars:
            ptr = frame.local_vars[program_var("DRIVER")].value
            base = getattr(ptr, "base", ptr)
            ws_handle = vm.heap_get(base).fields[WORKING_STORAGE_FIELD].value
            region = vm.region_get(Address(str(ws_handle)))
            assert region is not None, "DRIVER WS region missing"
            return int(region[0:4].decode("cp037"))
    raise AssertionError("DRIVER singleton not found in VM state")


@covers(CobolFeature.CALL_USING, CobolFeature.INTRINSIC_FUNCTION)
def test_ceedays_valid_date_severity_zero(tmp_path):
    """A valid Gregorian date (2024-01-15) yields feedback severity 0."""
    assert _run_and_read_sev(tmp_path, "2024-01-15") == 0


@covers(CobolFeature.CALL_USING, CobolFeature.INTRINSIC_FUNCTION)
def test_ceedays_leap_day_valid(tmp_path):
    """2024-02-29 is valid (2024 is a leap year) → severity 0."""
    assert _run_and_read_sev(tmp_path, "2024-02-29") == 0


@covers(CobolFeature.CALL_USING, CobolFeature.INTRINSIC_FUNCTION)
def test_ceedays_invalid_month_severity_nonzero(tmp_path):
    """Month 13 is invalid → nonzero severity (drives the caller's error path)."""
    assert _run_and_read_sev(tmp_path, "2024-13-15") != 0


@covers(CobolFeature.CALL_USING, CobolFeature.INTRINSIC_FUNCTION)
def test_ceedays_non_leap_day_invalid(tmp_path):
    """2023-02-29 is invalid (2023 is not a leap year) → nonzero severity."""
    assert _run_and_read_sev(tmp_path, "2023-02-29") != 0


@covers(CobolFeature.CALL_USING, CobolFeature.INTRINSIC_FUNCTION)
def test_ceedays_non_numeric_date_invalid(tmp_path):
    """A non-numeric date component → nonzero severity."""
    assert _run_and_read_sev(tmp_path, "20XX-01-15") != 0
