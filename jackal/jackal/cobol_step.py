"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from interpreter.address import Address
from interpreter.cobol.call_arguments import call_arguments
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.func_name import FuncName
from interpreter.project.entry_point import EntryPoint
from interpreter.project.types import LinkedProgram
from interpreter.run import (
    BudgetExhausted,
    RunOutcome,
    Suspended,
    initial_vm_state,
    run_linked_resumable,
)
from interpreter.run import Completed as RunCompleted
from interpreter.var_name import VarName
from interpreter.vm.vm_types import StackFrame, VMState
from jackal.allocation import DdEnvironment
from jackal.cobol_files import AllocatedFileIOProvider
from jackal.dataset import Relabeller
from jackal.model import ProgramStep, StepReference
from jackal.parm import build_parm_region
from jackal.program_compiler import CompiledProgram
from jackal.results import Abended, Completed, ProgramResult, SystemAbend
from jackal.value_parts import resolve

DEFAULT_PROGRAM_STEP_BUDGET = 500_000
CPU_TIME_EXCEEDED = SystemAbend(0x322)


class BatchProgramSuspended(Exception):
    """A batch COBOL program reached a SUSPEND, which only a CICS task can."""


def run_cobol_step(
    step: ProgramStep[StepReference],
    program: CompiledProgram,
    env: DdEnvironment,
    workdir: Path,
    budget: int,
    relabeller: Relabeller,
) -> ProgramResult:
    provider = AllocatedFileIOProvider(workdir, program.files, env, relabeller)
    outcome = run_linked_resumable(
        program.linked,
        _entry_point(program.linked),
        max_steps=budget,
        io_provider=provider,
        initial_vm=_initial_vm(step, provider),
    )
    return program_result(outcome)


def program_result(outcome: RunOutcome) -> ProgramResult:
    match outcome:
        case Suspended():
            raise BatchProgramSuspended()
        case _:
            return _ended(outcome)


def _ended(outcome: RunCompleted | BudgetExhausted) -> ProgramResult:
    match outcome:
        case RunCompleted(vm=vm):
            return Completed(read_return_code(vm))
        case BudgetExhausted():
            return Abended(CPU_TIME_EXCEEDED)


def _initial_vm(
    step: ProgramStep[StepReference], provider: AllocatedFileIOProvider
) -> VMState:
    return (
        _parm_vm(step, provider)
        if step.parm
        else initial_vm_state(io_provider=provider)
    )


def _parm_vm(
    step: ProgramStep[StepReference], provider: AllocatedFileIOProvider
) -> VMState:
    """A VM whose entry frame hands the program the PARM area as its first
    argument, which binds the first LINKAGE 01."""
    parm_addr = Address("rgn_parm")
    vm = VMState()
    vm.region_set(parm_addr, bytearray(build_parm_region(resolve(step.parm))))
    arguments = call_arguments(vm, [parm_addr])
    return replace(
        vm,
        io_provider=provider,
        call_stack=[
            StackFrame(
                function_name=FuncName("__jcl_entry__"),
                local_vars={VarName("__call_arguments"): arguments},
            )
        ],
    )


def _entry_point(linked: LinkedProgram) -> EntryPoint:
    """For COBOL, mirror run()'s entry-point switch: when func_symbol_table is
    populated, use function-entry mode so run_linked runs the init block (phase
    1, including RETURN-CODE region setup) then dispatches into the PROCEDURE
    DIVISION function (phase 2)."""
    procedures = [
        label
        for label in linked.func_symbol_table
        if not str(label).startswith("func_init_params_")
    ]
    if not procedures:
        return EntryPoint.top_level()
    entry = procedures[0]
    return EntryPoint.function(lambda ref: ref.label == entry)
