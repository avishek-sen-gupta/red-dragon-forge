"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from catnip.dataset import Relabeller
from interpreter.address import Address
from interpreter.cobol.call_arguments import call_arguments
from interpreter.cobol.program_object import ARGUMENTS_PARAM
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
from interpreter.vm.vm_types import StackFrame, VMState
from jackal.allocation import DdEnvironment
from jackal.cobol_files import AllocatedFileIOProvider
from jackal.le_abend import user_abend
from jackal.model import ProgramStep, StepReference, SystemAbend
from jackal.parm import build_parm_region
from jackal.program_compiler import CompiledProgram
from jackal.results import Abended, Completed, ProgramResult
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
            return _completed_or_abended(vm)
        case BudgetExhausted():
            return Abended(CPU_TIME_EXCEEDED)


def _completed_or_abended(vm: VMState) -> ProgramResult:
    abends = user_abend(vm)
    if abends:
        return Abended(abends[0])
    return Completed(read_return_code(vm))


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
                local_vars={ARGUMENTS_PARAM: arguments},
            )
        ],
    )


def _entry_point(linked: LinkedProgram) -> EntryPoint:
    """Enter the program at the entry label its compile recorded."""
    return EntryPoint.function(lambda ref: ref.label == linked.entry_func_label)
