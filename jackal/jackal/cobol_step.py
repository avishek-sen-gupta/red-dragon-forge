"""Run an EXEC PGM COBOL step against the red-dragon VM."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.address import Address
from interpreter.cobol.call_arguments import call_arguments
from interpreter.cobol.real_file_provider import RealFileIOProvider
from interpreter.cobol.return_code_readback import read_return_code
from interpreter.constants import Language
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.entry_point import EntryPoint
from interpreter.project.types import LinkedProgram
from interpreter.run import run, run_linked
from interpreter.var_name import VarName
from interpreter.vm.vm_types import StackFrame, VMState
from jackal.catalog import DatasetCatalog
from jackal.model import Step
from jackal.parm import build_parm_region
from jackal.results import StepDisposition, StepResult
from jackal.value_parts import resolve

# DDs whose absence is expected in the emulated environment and should be skipped
# silently rather than raising an error.
#   STEPLIB / JOBLIB — load-library DDs: real mainframe load libraries are never
#   present in the local file tree; the emulator finds programs via source_dir instead.
OPTIONAL_DDS: frozenset[str] = frozenset({"STEPLIB", "JOBLIB"})

MAX_STEPS = 500_000


def _file_control(source: str, parser: ProLeapCobolParser) -> list:
    return parser.parse(source.encode("utf-8")).file_control


def _overrides(step: Step, catalog: DatasetCatalog) -> dict[str, Path]:
    return {
        dd.ddname: catalog.allocate(dd).path
        for dd in step.dds
        if not dd.sysout and dd.ddname not in OPTIONAL_DDS
    }


def run_cobol_step(
    step: Step,
    source: str,
    catalog: DatasetCatalog,
    bridge_jar: str,
    copybook_dirs: Sequence[Path],
) -> StepResult:
    if not bridge_jar:
        raise ValueError(
            f"PROLEAP_BRIDGE_JAR not set; required to run COBOL step {step.name!r}"
        )
    parser = ProLeapCobolParser(
        runner=RealSubprocessRunner(),
        bridge_jar=bridge_jar,
        copybook_dirs=list(copybook_dirs),
    )
    provider = RealFileIOProvider(
        base_dir=catalog.workdir,
        file_control=_file_control(source, parser),
        path_overrides=_overrides(step, catalog),
    )
    vm = (
        _run_with_parm(step, source, parser, provider, copybook_dirs)
        if step.parm
        else _run_without_parm(source, provider, copybook_dirs)
    )
    for dd in step.dds:
        catalog.dispose(dd)
    return StepResult(
        name=step.name,
        return_code=read_return_code(vm),
        ran=True,
        disposition=StepDisposition.EXECUTED,
    )


def _run_with_parm(
    step: Step,
    source: str,
    parser: ProLeapCobolParser,
    provider: RealFileIOProvider,
    copybook_dirs: Sequence[Path],
) -> VMState:
    _, linked = compile_cobol(
        source.encode("utf-8"),
        parser=parser,
        copybook_dirs=list(copybook_dirs),
    )
    return run_linked(
        linked,
        _entry_point(linked),
        io_provider=provider,
        initial_vm=_parm_vm(step),
        max_steps=MAX_STEPS,
    )


def _run_without_parm(
    source: str, provider: RealFileIOProvider, copybook_dirs: Sequence[Path]
) -> VMState:
    return run(
        source,
        language=Language.COBOL,
        io_provider=provider,
        max_steps=MAX_STEPS,
        copybook_dirs=list(copybook_dirs),
    )


def _parm_vm(step: Step) -> VMState:
    """A VM whose entry frame hands the program the PARM area as its first
    argument, which binds the first LINKAGE 01."""
    parm_addr = Address("rgn_parm")
    vm = VMState()
    vm.region_set(parm_addr, bytearray(build_parm_region(resolve(step.parm))))
    arguments = call_arguments(vm, [parm_addr])
    return replace(
        vm,
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
