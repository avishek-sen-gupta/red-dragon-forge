"""cobol_harness reads a program's own fields, never the run unit's region that every COBOL run allocates first."""

from __future__ import annotations

from cobol_asg.cobol_parser import make_cobol_parser
from cobol_harness.state import read_vm_field
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.entry_point import EntryPoint
from interpreter.run import initial_vm_state, run_linked
from interpreter.vm.builtins import core_builtins

_PROGRAM = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. HSTATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CODE PIC X(2) VALUE 'OK'.
       PROCEDURE DIVISION.
           MOVE 'GO' TO WS-CODE.
           GOBACK.
"""


def test_read_vm_field_reads_working_storage_not_the_run_unit_region():
    linked = compile_cobol(_PROGRAM, parser=make_cobol_parser())
    vm = run_linked(
        linked,
        EntryPoint.function(lambda f: str(f.name) == "func_hstate_0"),
        max_steps=10_000,
        initial_vm=initial_vm_state(),
        builtins=core_builtins(),
    )
    assert read_vm_field(vm, "WS-CODE") == "GO".encode("cp037")
