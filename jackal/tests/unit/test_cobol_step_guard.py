"""Unit guards: compiling needs PROLEAP_BRIDGE_JAR; a batch program cannot suspend."""

from __future__ import annotations

import pytest
from interpreter.ir import CodeLabel
from interpreter.register import Register
from interpreter.run import ExecutionState, Suspended, initial_vm_state
from jackal.cobol_step import BatchProgramSuspended, program_result
from jackal.program_compiler import ProgramCompiler
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_compiling_a_cobol_program_with_an_empty_bridge_jar_fails_loud():
    with pytest.raises(ValueError, match="PROLEAP_BRIDGE_JAR"):
        ProgramCompiler("", (), (), ()).compiled("irrelevant")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_batch_program_that_suspends_is_refused():
    state = ExecutionState(initial_vm_state(), CodeLabel("entry"), 0, Register("%0"))
    with pytest.raises(BatchProgramSuspended):
        program_result(Suspended(state, None))
