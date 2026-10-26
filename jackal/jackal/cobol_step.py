"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from catnip.dataset import Relabeller
from infrastructure.zos.abend.system_abend import SystemAbend
from interpreter.address import Address
from interpreter.cobol.call_arguments import call_arguments
from interpreter.cobol.cee3abd_abend import user_abend
from interpreter.cobol.io_provider import CobolIOProvider
from interpreter.cobol.program_object import ARGUMENTS_PARAM
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.func_name import FuncName
from interpreter.project.program_entry import ProgramEntry
from interpreter.project.types import LinkedProgram
from interpreter.run import (
    BudgetExhausted,
    RunOutcome,
    Suspended,
    initial_vm_state,
    run_linked_resumable,
)
from interpreter.run import Completed as RunCompleted
from interpreter.vm.builtin import Builtin
from interpreter.vm.vm_types import StackFrame, VMState
from jackal.allocation import DdEnvironment
from jackal.cobol_files import AllocatedFileIOProvider
from jackal.model import ProgramStep, StepReference
from jackal.parm import build_parm_region
from jackal.results import Abended, Completed, ProgramResult
from jackal.value_parts import resolve
from zos.cobol.io.program_file import ProgramFile
from zos.cobol.io.program_files import ProgramFilesIOProvider

DEFAULT_PROGRAM_STEP_BUDGET = 500_000
CPU_TIME_EXCEEDED = SystemAbend(0x322)


@dataclass(frozen=True)
class CompiledProgram:
    linked: LinkedProgram
    entry: ProgramEntry
    files: tuple[ProgramFile, ...]


class BatchProgramSuspended(Exception):
    """A batch COBOL program reached a SUSPEND, which only a CICS task can."""


def run_cobol_step(
    step: ProgramStep[StepReference],
    program: CompiledProgram,
    env: DdEnvironment,
    workdir: Path,
    budget: int,
    relabeller: Relabeller,
    *,
    builtins: Mapping[FuncName, Builtin],
    permit_unresolved_call_targets: bool = True,
) -> ProgramResult:
    provider = ProgramFilesIOProvider(
        tuple(program.linked.programs),
        partial(AllocatedFileIOProvider, workdir, env=env, relabeller=relabeller),
        program.files,
    )
    outcome = run_linked_resumable(
        program.linked,
        program.entry,
        max_steps=budget,
        builtins=builtins,
        initial_vm=_initial_vm(step, provider),
        permit_unresolved_call_targets=permit_unresolved_call_targets,
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


def _initial_vm(step: ProgramStep[StepReference], provider: CobolIOProvider) -> VMState:
    return (
        _parm_vm(step, provider)
        if step.parm
        else initial_vm_state(io_provider=provider)
    )


def _parm_vm(step: ProgramStep[StepReference], provider: CobolIOProvider) -> VMState:
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
