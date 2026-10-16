"""Unit guard: a batch program cannot suspend."""

from __future__ import annotations

import pytest
from interpreter.ir import CodeLabel
from interpreter.register import Register
from interpreter.run import ExecutionState, Suspended, initial_vm_state
from jackal.cobol_step import BatchProgramSuspended, program_result
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_batch_program_that_suspends_is_refused():
    state = ExecutionState(
        initial_vm_state(), CodeLabel("entry"), 0, Register("%0"), CodeLabel("entry")
    )
    with pytest.raises(BatchProgramSuspended):
        program_result(Suspended(state, None))
