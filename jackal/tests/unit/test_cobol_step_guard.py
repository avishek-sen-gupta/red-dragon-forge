"""Unit guard: a COBOL step must fail loud when PROLEAP_BRIDGE_JAR is unset."""

from __future__ import annotations

import pytest
from interpreter.ir import CodeLabel
from interpreter.register import Register
from interpreter.run import ExecutionState, Suspended, initial_vm_state
from jackal.allocation import DdEnvironment
from jackal.cobol_step import (
    DEFAULT_PROGRAM_STEP_BUDGET,
    BatchProgramSuspended,
    program_result,
    run_cobol_step,
)
from tests.covers import NotLanguageFeature, covers
from tests.model_build import program
from tests.system_build import job_catalog


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_cobol_step_empty_bridge_jar_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="PROLEAP_BRIDGE_JAR"):
        run_cobol_step(
            program("S", "P"),
            "irrelevant",
            DdEnvironment(()),
            tmp_path,
            "",
            [],
            DEFAULT_PROGRAM_STEP_BUDGET,
            job_catalog(tmp_path),
        )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_batch_program_that_suspends_is_refused():
    state = ExecutionState(initial_vm_state(), CodeLabel("entry"), 0, Register("%0"))
    with pytest.raises(BatchProgramSuspended):
        program_result(Suspended(state, None))
